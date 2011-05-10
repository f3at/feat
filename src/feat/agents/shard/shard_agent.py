# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import operator

from feat.agents.base import (agent, message, contractor, manager, recipient,
                              replay, partners, resource, document, dbtools,
                              task, poster, notifier)
from feat.agents.common import rpc, raage, host, monitor
from feat.common import fiber, defer, serialization, manhole, enum

from feat.interface.protocols import *
from feat.interface.contracts import *


@serialization.register
class HostPartner(agent.BasePartner):

    type_name = 'shard->host'

    def initiate(self, agent):
        # Host Agent on the other end is about to join our shard,
        # his address will change.
        shard = agent.get_own_address().shard
        self.recipient = recipient.Agent(self.recipient.key, shard)

        if self.allocation_id is None:
            f = agent.allocate_resource(hosts=1)
            f.add_callback(self.set_allocation_id)
            return f

    def set_allocation_id(self, allocation):
        self.allocation_id = allocation.id


@serialization.register
class ShardPartner(agent.BasePartner):

    type_name = 'shard->neighbour'

    def initiate(self, agent):
        agent.on_new_neighbour(self.recipient)
        if self.allocation_id is None:
            f = agent.allocate_resource(neighbours=1)
            f.add_callback(self._store_alloc_id)
            return f

    def startup(self):
        agent.BaseAgent.startup(self)
        self.startup_monitoring()

    def _store_alloc_id(self, alloc):
        assert isinstance(alloc, resource.Allocation)
        self.allocation_id = alloc and alloc.id

    def on_goodbye(self, agent, brothers):
        d = defer.succeed(self)
        d.addCallback(partners.BasePartner.on_goodbye, agent)
        d.addBoth(defer.drop_param, agent.become_king)
        d.addBoth(defer.drop_param, agent.on_neighbour_gone, self.recipient)
        d.addBoth(defer.drop_param, agent.look_for_neighbours)
        return d


class StructuralPartner(agent.BasePartner):
    '''
    Abstract base class for all the partners which should be started and
    managed by Shard Agent.
    '''

    @classmethod
    def discover(cls, agent):
        '''
        Should return a fiber which results in a list of agents of this type
        available in the shard.
        '''
        raise NotImplementedError('Should be overloaded')

    @classmethod
    def prepare_descriptor(cls, agent):
        '''
        Should return a fiber which results in a saved descriptor in the
        database.
        '''
        raise NotImplementedError('Should be overloaded')

    def on_goodbye(self, agent, brothers):
        #FIXME: on_goodbye should return a deferred
        return fiber.maybe_fiber(agent.fix_shard_structure)

    def on_died(self, agent, brothers, monitor):
        task = agent.request_restarting_partner(self.recipient.key, monitor)
        return partners.accept_responsability(task)


@serialization.register
class RaagePartner(StructuralPartner):

    type_name = 'shard->raage'

    @classmethod
    def discover(cls, agent):
        return raage.discover(agent)

    @classmethod
    def prepare_descriptor(cls, agent):
        desc = raage.Descriptor()
        return agent.save_document(desc)


@serialization.register
class MonitorPartner(monitor.PartnerMixin, StructuralPartner):

    type_name = 'shard->monitor'

    @classmethod
    def discover(cls, agent):
        return monitor.discover(agent)

    @classmethod
    def prepare_descriptor(cls, agent):
        desc = monitor.Descriptor()
        return agent.save_document(desc)

    def on_goodbye(self, agent, brothers):
        d = defer.succeed(None)
        d.addCallback(defer.drop_param,
                      monitor.PartnerMixin.on_goodbye, self, agent, brothers)
        d.addCallback(defer.drop_param,
                      StructuralPartner.on_goodbye, self, agent, brothers)
        return d


class Partners(agent.Partners):

    partners.has_many('hosts', 'host_agent', HostPartner)
    partners.has_many('neighbours', 'shard_agent', ShardPartner)
    partners.has_one('raage', 'raage_agent', RaagePartner)
    partners.has_one('monitor', 'monitor_agent', MonitorPartner)

    shard_structure = ['raage_agent', 'monitor_agent']


class ShardAgentRole(enum.Enum):
    '''
    king - a shard being the entry point (lobby binding)
    peasant - normal shard
    '''
    (king, peasant, ) = range(2)


@document.register
class ShardAgentConfiguration(document.Document):

    document_type = 'shard_agent_conf'
    document.field('doc_id', u'shard_agent_conf', '_id')
    document.field('hosts_per_shard', 10)
    document.field('neighbours', 3)


dbtools.initial_data(ShardAgentConfiguration)


@agent.register('shard_agent')
class ShardAgent(agent.BaseAgent, rpc.AgentMixin, notifier.AgentMixin):

    partners_class = Partners

    restart_strategy = monitor.RestartStrategy.local

    @replay.entry_point
    def initiate(self, state):
        agent.BaseAgent.initiate(self)
        rpc.AgentMixin.initiate(self)
        notifier.AgentMixin.initiate(self, state)

        config = state.medium.get_configuration()

        state.resources.define('hosts', config.hosts_per_shard)
        state.resources.define('neighbours', config.neighbours)

        state.join_interest =\
            state.medium.register_interest(
            contractor.Service(JoinShardContractor))
        state.medium.register_interest(JoinShardContractor)

        state.neighbour_interest =\
            state.medium.register_interest(
            contractor.Service(FindNeighboursContractor))
        state.medium.register_interest(FindNeighboursContractor)

        state.medium.register_interest(QueryStructureContractor)

        # Creates shard's notifications poster
        shard = self.get_own_address().shard
        recp = recipient.Broadcast(ShardNotificationPoster.protocol_id, shard)
        state.poster = self.initiate_protocol(ShardNotificationPoster, recp)

        state.tasks = {}
        state.role = None
        self.become_king()

        return self.initiate_partners()

    @replay.mutable
    def startup(self, state):
        agent.BaseAgent.startup(self)
        f = self.look_for_neighbours()
        f.add_callback(fiber.drop_param, self.fix_shard_structure)
        return f

    @replay.mutable
    def fix_shard_structure(self, state):
        for partner_class in state.partners.shard_structure:
            factory = self.query_partner_handler(partner_class)
            if factory in state.tasks:
                continue
            partner = self.query_partners(factory)
            if partner is None or (isinstance(partner, list) and \
               len(partner) == 0):
                self.debug("fix_shard_structure() detected missing %r "
                           "partner, taking action.", partner_class)
                task = self.initiate_protocol(FixMissingPartner, factory)
                state.tasks[factory] = task
        return self.wait_for_structure()

    @replay.immutable
    def wait_for_structure(self, state):
        if state.tasks:
            return self.wait_for_event("partners_fixed")
        return fiber.succeed(self)

    @replay.mutable
    def _partner_fixed(self, state, factory):
        del state.tasks[factory]
        if not state.tasks:
            self.callback_event("partners_fixed", self)

    @replay.mutable
    def request_starting_partner(self, state, factory):
        task = self.initiate_protocol(StartPartner, factory)
        return fiber.wrap_defer(task.notify_finish)

    @replay.mutable
    def request_restarting_partner(self, state, agent_id, monitor=None):
        task = self.initiate_protocol(RestartPartner, agent_id, monitor)
        return task

    @manhole.expose()
    @rpc.publish
    @replay.journaled
    def query_structure(self, state, partner_type, distance=1):

        def swallow_initiator_failed(fail):
            fail.trap(ProtocolFailed)
            self.debug('query_structure failed with %r, returning empty '
                       'list', fail)
            return list()

        if distance != 1:
            agent.error('Query distance is not supported yet. Right now '
                        'this parameter is ignored and defaults to 1')
            distance = 1

        manager = self.initiate_protocol(
            QueryStructureManager, state.partners.neighbours,
            partner_type, distance)

        f = manager.notify_finish()
        f.add_errback(swallow_initiator_failed)
        return f

    @manhole.expose()
    @rpc.publish
    @replay.journaled
    def get_host_list(self, state):
        return state.partners.hosts

    @manhole.expose()
    @replay.journaled
    def look_for_neighbours(self, state):
        f = self.discover_service(FindNeighboursManager, timeout=2)
        f.add_callback(
            lambda recp: self.initiate_protocol(FindNeighboursManager, recp))
        f.add_callback(FindNeighboursManager.notify_finish)
        f.add_errback(self.look_for_failed)
        return f

    @rpc.publish
    def propose_to(self, recp, partner_role=None, our_role=None):
        return agent.BaseAgent.propose_to(self, recp, partner_role, our_role)

    def look_for_failed(self, f):
        self.info('Look for neighbours contract failed. Reason: %r', f)

    @rpc.publish
    def substitute_partner(self, *args, **kwargs):
        return agent.BaseAgent.substitute_partner(self, *args, **kwargs)

    @rpc.publish
    def release_resource(self, alloc_id):
        return agent.BaseAgent.release_resource(self, alloc_id)

    @manhole.expose()
    @replay.mutable
    def divorce_action(self, state, to_divorce, to, alloc_ids):
        '''
        Divorces one shard partner telling him to put other partner in the
        middle.
        @param to_divorce: IRecipient of shard partner to divorce
        @param to: IRecipient of shard to put into middle
        @param alloc_ids: list of 2 ids to store on the side of joining agent
        @return: Fiber
        '''
        assert isinstance(alloc_ids, (list, tuple, ))
        assert len(alloc_ids) == 2
        own = self.get_own_address()
        f = self.call_remote(to_divorce, 'substitute_partner', own, to,
                             alloc_ids[0])
        f.add_errback(self._mind_double_partnership, to, alloc_ids[0])
        f.add_callback(fiber.drop_param, self.call_remote, to_divorce,
                       'check_your_role')
        f.add_callback(fiber.drop_param, self.substitute_partner,
                       to_divorce, to, alloc_ids[1])
        f.add_errback(self._mind_double_partnership, to, alloc_ids[1])
        f.add_callback(fiber.drop_param, self.become_peasant)
        return f

    def _mind_double_partnership(self, fail, recp, alloc_id):
        if fail.check(partners.DoublePartnership):
            return self.call_remote(recp, 'release_resource', alloc_id)
        else:
            fail.raiseException()

    ### Notification Methods ###

    @replay.immutable
    def on_new_neighbour(self, state, shard):
        state.poster.new_neighbour(shard)

    @replay.immutable
    def on_neighbour_gone(self, state, shard):
        state.poster.neighbour_gone(shard)

    ### Managing the shard agents role ###

    @rpc.publish
    @replay.mutable
    def check_your_role(self, state):
        '''
        Called by the partner divorcing us. We should become a peasant if we
        have 3 neighbours already.
        '''
        if len(state.partners.neighbours) == 3:
            self.become_peasant()

    @replay.mutable
    def become_king(self, state):
        if not self.is_king():
            state.neighbour_interest.bind_to_lobby()
            state.join_interest.bind_to_lobby()
            state.role = ShardAgentRole.king

    @replay.mutable
    def become_peasant(self, state):
        if not self.is_peasant():
            state.neighbour_interest.unbind_from_lobby()
            state.join_interest.unbind_from_lobby()
            state.role = ShardAgentRole.peasant

    @replay.immutable
    def get_role(self, state):
        return state.role

    @replay.immutable
    def cmp_role(self, state, role):
        return state.role == role

    def is_king(self):
        return self.cmp_role(ShardAgentRole.king)

    def is_peasant(self):
        return self.cmp_role(ShardAgentRole.peasant)

    ### end of role related methods ###


class SolutionType(enum.Enum):
    (join, divorce, ) = range(2)


@serialization.register
class FindNeighboursContractor(contractor.BaseContractor):

    bid_timeout = 6

    protocol_id = 'find-neighbours'
    concurrency = 1

    @replay.entry_point
    def announced(self, state, announcement):
        if self._is_own_announcement(announcement):
            self._refuse()
            return

        allocation = state.agent.preallocate_resource(neighbours=1)
        my_neighbours = self._get_neighbours_ids()
        if allocation is None and \
           not (len(my_neighbours) >= 2 and state.agent.is_king()):
            self._refuse()
            return

        msg = message.Bid()
        msg.payload['my_neighbours'] = my_neighbours
        if allocation:
            msg.payload['solution_type'] = SolutionType.join
            msg.payload['cost'] = len(my_neighbours)
        else:
            msg.payload['solution_type'] = SolutionType.divorce
            msg.payload['cost'] = 10
        state.medium.bid(msg)
        state.allocation_id = allocation and allocation.id

    @replay.mutable
    def _release_allocation(self, state, *_):
        if state.allocation_id:
            return state.agent.release_resource(state.allocation_id)

    expired = _release_allocation
    rejected = _release_allocation
    cancelled = _release_allocation

    @replay.entry_point
    def granted(self, state, grant):
        recp = grant.payload['joining_agent']
        if grant.payload['solution_type'] == SolutionType.join:
            f = state.agent.confirm_allocation(state.allocation_id)
            f.add_callback(fiber.drop_param,
                           state.agent.establish_partnership, recp,
                           state.allocation_id,
                           grant.payload['allocations'][0])
            f.add_callbacks(self._finalize, self._granted_failed)
            return f
        elif grant.payload['solution_type'] == SolutionType.divorce:
            f = state.agent.divorce_action(grant.payload['to_divorce'], recp,
                                           grant.payload['allocations'])
            f.add_callbacks(self._finalize, self._granted_failed)
            return f
        else:
            raise NotImplementedError(
                "Unknown solution type: %r", grant.payload['solution_type'])

    def aborted(self):
        # TODO: divorce the partner when this is implemented
        pass

    @replay.immutable
    def _granted_failed(self, state, failure):
        #FIXME: guard against expiration, should use fiber cancellation
        state.medium.ensure_state(ContractState.granted)
        state.medium._error_handler(failure)
        msg = message.Cancellation(reason=str(failure.value))
        state.medium.defect(msg)
        return self._release_allocation()

    @replay.immutable
    def _finalize(self, state, _):
        #FIXME: guard against expiration, should use fiber cancellation
        state.medium.ensure_state(ContractState.granted)
        report = message.FinalReport()
        state.medium.finalize(report)

    # private

    @replay.immutable
    def _refuse(self, state):
        msg = message.Refusal()
        state.medium.refuse(msg)

    @replay.immutable
    def _get_neighbours_ids(self, state):
        return map(lambda x: x.recipient,
                   state.agent.query_partners('neighbours'))

    @replay.immutable
    def _is_own_announcement(self, state, announcement):
        own = state.agent.get_own_address()
        return announcement.payload['joining_agent'] == own


@serialization.register
class FindNeighboursManager(manager.BaseManager):

    protocol_id = 'find-neighbours'

    announce_timeout = 3
    grant_timeout = 3

    @replay.entry_point
    def initiate(self, state):
        msg = message.Announcement()
        msg.payload['joining_agent'] = state.agent.get_own_address()
        state.medium.announce(msg)
        state.allocations = list()

    @replay.entry_point
    def closed(self, state):
        # Try to get at least 2 and preferable 3 join bids.
        # If thats imposible get the best divorce bid.
        bids = state.medium.get_bids()
        bids = self._remove_incorrect_choices(bids)
        cat = self._categorize(bids)
        joins = message.Bid.pick_best(cat[SolutionType.join], 3)
        best_divorce = self._pick_divorce_bid(cat[SolutionType.divorce], bids)
        free_slots = self._count_free_slots()
        to_grant = list()
        slots_needed = 0

        if free_slots == 0:
            self.info("We don't have any place for new neighbours. "
                      "Terminating")
            state.medium.terminate()
            return
        elif free_slots == 1:
            if len(joins) > 0:
                to_grant = [joins[0]]
                slots_needed = 1
            else:
                self.info("Only one free slot and no join bids. Terminating.")
                state.medium.terminate()
                return
        else:
            if len(joins) > 1:
                to_grant = joins[0:free_slots]
                slots_needed = len(to_grant)
            elif best_divorce is not None:
                to_grant = [best_divorce]
                slots_needed = 2
            elif len(joins) == 1:
                to_grant = [joins[0]]
                slots_needed = len(to_grant)
            else:
                self.info("We didn't receive any bids. Maybe we are the first"
                          " shard?")
                state.medium.terminate()
                return
        f = fiber.succeed()
        f.add_callback(fiber.drop_param, self._allocate_slots, slots_needed)
        f.add_callback(fiber.drop_param, self._prepare_grants, to_grant)
        f.add_callback(state.medium.grant)
        return f

    @replay.entry_point
    def completed(self, state, reports):
        pass

    @replay.mutable
    def _release_unused_allocations(self, state, *_):
        # FIXME: possible n HTTP requests
        f = fiber.succeed()
        for alloc_id in state.allocations:
            if not state.agent.allocation_used(alloc_id):
                f.add_callback(fiber.drop_param,
                               state.agent.release_resource,
                               alloc_id)
        return f

    cancelled = _release_unused_allocations
    aborted = _release_unused_allocations

    # private

    @replay.immutable
    def _get_incorrect_choices(self, state):
        '''
        Get the list of currect partners IRecipient and our address.
        '''
        return [state.agent.get_own_address()] +\
               map(operator.attrgetter('recipient'),
                   state.agent.query_partners('neighbours'))

    def _remove_incorrect_choices(self, bids):
        '''
        Remove all the bids coming from existing partners.
        '''
        incorrect_choices = self._get_incorrect_choices()
        resp = list()
        for bid in bids:
            # check if it comes from sth we don't want
            if bid.reply_to in incorrect_choices:
                continue
            resp.append(bid)
        return resp

    @replay.mutable
    def _allocate_slots(self, state, needed):
        for x in range(needed):
            al = state.agent.preallocate_resource(neighbours=1)
            state.allocations.append(al.id)
        f = fiber.succeed()
        # FIXME: n HTTP requests - we need a bulk confirm resource here
        for a_id in state.allocations:
            f.add_callback(fiber.drop_param,
                           state.agent.confirm_allocation, a_id)
        return f

    @replay.immutable
    def _count_free_slots(self, state):
        totals, alloc = state.agent.list_resource()
        return totals['neighbours'] - alloc['neighbours']

    def _pick_divorce_bid(self, divorce_bids, all_bids):
        '''
        This methods tries to find a bid for divorcing a partner who is
        also a king. The implementation uses the fact the if someone is
        a king we should have received a bid from him. This is true unless
        we have a network problem.
        For each contractor the method creates a tuple:
        (num_of_partners, num_of_king_partners, )
        We will be divorcing the shard with the highest value with its partner
        of the highest value. In case we miss the information (bid) for some
        shard we assume a tuple of (3, 0) for him.
        '''
        if divorce_bids is None or len(divorce_bids) == 0:
            return None

        # agent_id -> divorce_bid
        divorce_bids = dict(map(lambda x: (x.reply_to.key, x, ), divorce_bids))
        # agent_id -> list_of_neighbours
        neighbours = dict(map(
            lambda x: (x.reply_to.key, x.payload['my_neighbours'], ),
            all_bids))
        # agent_id -> number_of_king_neighbours
        num_kings = dict(map(
            lambda x: (x.reply_to.key, len(
                filter(lambda y: y.key in neighbours.keys(),
                       x.payload['my_neighbours'])), ),
            all_bids))
        # agent_id -> (num_of_neighbours, num_of_king_neighbours, )
        shard_info = dict(map(
            lambda x: (x, (len(neighbours[x]), num_kings[x], ), ),
            num_kings.keys()))
        # (agent_id, neighbour_recp, ) ->
        #                    (num_of_neigh, num_of_kings, same_for_neighbour)
        possible_divorces = dict()
        # list of IRecpients off incorrect choices
        incorrect_choices = self._get_incorrect_choices()
        for divorcer, values in shard_info.iteritems():
            for neighbour in neighbours[divorcer]:
                if neighbour in incorrect_choices:
                    continue
                if divorcer not in divorce_bids:
                    continue
                neighbour_values = shard_info.get(neighbour.key, (3, 0, ))
                possible_divorces[(divorcer, neighbour, )] =\
                                             values + neighbour_values
        if len(possible_divorces.keys()) == 0:
            return None
        sorted_tuples = sorted(possible_divorces.items(),
                               key=lambda x: x[1] + (x[0][0], x[0][1].key, ),
                               reverse=True)
        to_grant = divorce_bids[sorted_tuples[0][0][0]]
        to_grant.payload['my_neighbours'] = [sorted_tuples[0][0][1]]
        return to_grant

    def _categorize(self, bids):
        resp = dict()
        for typ in SolutionType.iterkeys():
            resp[typ] = list()
        for bid in bids:
            typ = bid.payload['solution_type']
            resp[typ].append(bid)
        return resp

    @replay.mutable
    def _prepare_grants(self, state, to_grant):
        res = list()
        for bid in to_grant:
            res.append((bid, self._prepare_grant(bid), ))
        return res

    @replay.mutable
    def _prepare_grant(self, state, bid):
        msg = message.Grant()
        msg.payload['joining_agent'] = state.agent.get_own_address()
        s_t = bid.payload['solution_type']
        msg.payload['solution_type'] = s_t
        msg.payload['allocations'] = [state.allocations.pop(0)]
        if s_t == SolutionType.divorce:
            msg.payload['to_divorce'] = bid.payload['my_neighbours'][0]
            # divorce requires two allocations
            msg.payload['allocations'].append(state.allocations.pop(0))
        return msg


@serialization.register
class JoinShardContractor(contractor.NestingContractor):

    protocol_id = 'join-shard'
    concurrency = 1

    @replay.mutable
    def announced(self, state, announcement):
        allocation = state.agent.preallocate_resource(hosts=1)

        if allocation is not None:
            state.preallocation_id = allocation.id
            bid = message.Bid()
            # we want to favor filling up the farthers
            # shards from the entry point
            bid.payload['cost'] = -announcement.level
        else:
            bid = None

        f = fiber.Fiber()

        f.add_callback(fiber.drop_param, self.fetch_nested_bids,
                       state.agent.query_partners('neighbours'), announcement)
        f.add_callback(self._pick_best_bid, bid)
        f.add_callback(self._bid_refuse_or_handover, bid)
        f.add_callback(fiber.drop_param, self.terminate_nested_manager)
        return f.succeed()

    @replay.immutable
    def _pick_best_bid(self, state, nested_bids, own_bid):
        # prepare the list of bids
        bids = list()
        if own_bid:
            bids.append(own_bid)
        if nested_bids is None:
            nested_bids = list()
        bids += nested_bids
        self.log('_pick_best_bid analizes total of %d bids', len(bids))

        # check if we have received anything
        if len(bids) == 0:
            self.info('Did not receive any bids to evaluate! '
                      'Contract will fail.')
            return None

        # elect best bid
        return message.Bid.pick_best(bids)[0]

    @replay.journaled
    def _bid_refuse_or_handover(self, state, bid=None, original_bid=None):
        if bid is None:
            refusal = message.Refusal()
            return state.medium.refuse(refusal)
        elif bid == original_bid:
            state.bid = bid
            return state.medium.bid(bid)
        else:
            f = fiber.Fiber()
            f.add_callback(self.release_preallocation)
            f.add_callback(fiber.drop_param, self.handover, bid)
            return f.succeed()

    @replay.immutable
    def release_preallocation(self, state, *_):
        if getattr(state, 'preallocation_id', None):
            return state.agent.release_resource(state.preallocation_id)

    announce_expired = release_preallocation
    rejected = release_preallocation
    expired = release_preallocation

    @replay.mutable
    def granted(self, state, grant):
        f = fiber.succeed(state.preallocation_id)
        f.add_callback(state.agent.confirm_allocation)
        f.add_callback(
            fiber.drop_param, state.agent.establish_partnership,
            grant.payload['joining_agent'], state.preallocation_id)
        f.add_callback(state.medium.update_manager_address)
        f.add_callbacks(self._finalize, self._granted_failed)
        return f

    def _granted_failed(self, failure):
        self.release_preallocation()
        failure.raiseException()

    @replay.immutable
    def _finalize(self, state, _):
        report = message.FinalReport()
        state.medium.finalize(report)


class FixMissingPartner(task.BaseTask):

    protocol_id = 'shard_agent.fix-missing-partner'
    timeout = 20

    @replay.entry_point
    def initiate(self, state, factory):
        state.factory = factory
        f = factory.discover(state.agent)
        f.add_callback(self.request_starting_partner_if_necessary)
        f.add_callback(state.agent.establish_partnership)
        f.add_both(fiber.bridge_param,
                   state.agent._partner_fixed, state.factory)
        return f

    @replay.immutable
    def request_starting_partner_if_necessary(self, state, discovered):
        if len(discovered) == 1:
            return discovered[0]
        elif len(discovered) > 1:
            # FIXME: At this point using alerts would be a good idea
            self.warning('Discovery returned %d partners of the factory %r. '
                         'Something is clearly wrong!', len(discovered),
                         state.factory)
            return discovered[0]
        else:
            return state.agent.request_starting_partner(state.factory)


class StartPartnerException(Exception):
    pass


class AbstractStartPartner(task.BaseTask):
    """
    Base class for StartPartner and RestartPartner tasks.
    Implements common functionality which is cyclying through the list of
    host partners and requesting the to start the agent.
    """

    timeout = 60

    def initiate(self):
        raise NotImplementedError('Abstract class, implement me.')

    @replay.mutable
    def _try_next(self, state):
        state.current_index += 1
        try:
            partner = state.hosts[state.current_index]
        except IndexError:
            return self._fail(
                'No of the Host Partners managed to start a partner %r' %\
                (state.descriptor.document_type, ))

        f = host.start_agent(state.agent, partner, state.descriptor)
        f.add_errback(self._failed_to_start, partner)
        return f

    @replay.immutable
    def _failed_to_start(self, state, fail, partner):
        self.error('Failed to start %r on partner %r. Reason: %r. Will retry '
                   'with the next', state.descriptor.document_type, partner,
                   fail)
        return self._try_next()

    def _fail(self, msg):
        self.error(msg)
        return fiber.fail(StartPartnerException(msg))

    @replay.mutable
    def _store_descriptor(self, state, desc):
        state.descriptor = desc
        return desc

    @replay.mutable
    def _init(self, state, initiate_arg):
        '''
        Set initial state of the task. Called from initiate.
        @param initiate_arg: either the PartnerClass object (StartTask)
                             or an agent_id (RestartTask)
        '''
        state.descriptor = None
        state.hosts = state.agent.query_partners('hosts')
        state.current_index = -1

        self.log('%s task initiated, will be trying to start a '
                 '%r on one of the hosts: %r', str(self.__class__.__name__),
                 initiate_arg, state.hosts)
        if len(state.hosts) == 0:
            # FIXME: Here would be a good idea to put an alert
            return self._fail('Shard Agent cannot start partner %r as it has '
                              'no Host Partners!' % (initiate_arg, ))


class StartPartner(AbstractStartPartner):

    protocol_id = 'request-starting-partner'

    @replay.entry_point
    def initiate(self, state, factory):
        self._init(factory)

        f = factory.prepare_descriptor(state.agent)
        f.add_callback(self._store_descriptor)
        f.add_callback(fiber.drop_param, self._try_next)
        return f


class RestartPartner(AbstractStartPartner):

    protocol_id = 'request-restarting-partner'

    @replay.entry_point
    def initiate(self, state, agent_id, monitor):
        self._init(agent_id)
        state.monitor = monitor

        f = state.agent.get_document(agent_id)
        f.add_callback(self._store_descriptor)
        f.add_callback(self._remove_host_partner)
        f.add_callback(fiber.drop_param, self._try_next)
        f.add_callback(self._notify_monitor)
        return f

    @replay.mutable
    def _remove_host_partner(self, state, desc):
        f = desc.remove_host_partner(state.agent)
        f.add_callback(self._store_descriptor)
        return f

    @replay.immutable
    def _notify_monitor(self, state, recp):
        return state.agent.call_remote(state.monitor, 'restart_complete',
                                       recp)


class QueryStructureManager(manager.BaseManager):

    protocol_id = 'query-structure'

    announce_timeout = 3

    @replay.entry_point
    def initiate(self, state, partner_type, distance):
        payload = dict(partner_type=partner_type, distance=distance)
        msg = message.Announcement(payload=payload)
        state.medium.announce(msg)

    @replay.immutable
    def closed(self, state):
        bids = state.medium.get_bids()
        result = list()
        for bid in bids:
            result += bid.payload['partners']
        state.medium.terminate(result)


class QueryStructureContractor(contractor.BaseContractor):

    protocol_id = 'query-structure'

    @replay.entry_point
    def announced(self, state, announcement):
        # FIXME: Eventually this contract should be a NestedContractor, which
        # would compare the announcement.level and
        # announcement.payload.distance, nest contract in necessary and
        # consolidate the bids. This way we will get the tree decomposition
        # of the graph for the arbitrary structure agent type
        partner_type = announcement.payload['partner_type']

        f = fiber.succeed()
        f.add_callback(fiber.drop_param, state.agent.wait_for_structure)
        # Ensure that nothing is called if the protocol timeout
        f.add_callback(fiber.bridge_param, state.medium.ensure_state,
                       ContractState.announced)
        f.add_callback(fiber.drop_param, self._query_partners, partner_type)
        return f

    @replay.immutable
    def _query_partners(self, state, partner_type):
        factory = state.agent.query_partner_handler(partner_type)
        partners = state.agent.query_partners(factory)

        payload = dict(partners=partners)
        msg = message.Bid(payload=payload)
        state.medium.bid(msg)


class ShardNotificationPoster(poster.BasePoster):

    protocol_id = 'shard-notification'

    @replay.immutable
    def neighbour_gone(self, state, shard):
        self.notify("neighbour_gone", shard)

    @replay.immutable
    def new_neighbour(self, state, shard):
        self.notify("new_neighbour", shard)

    ### Overridden Methods ###

    def pack_payload(self, name, *args):
        return (name, args)
