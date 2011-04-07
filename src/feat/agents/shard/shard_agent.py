# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import operator

from feat.agents.base import (agent, message, contractor, manager, recipient,
                              descriptor, replay, partners, resource, )
from feat.agents.common import host, rpc
from feat.common import fiber, serialization, manhole, enum
from feat.interface.protocols import InterestType
from feat.interface.contracts import ContractState
from feat.agents.common import shard


@serialization.register
class HostPartner(partners.BasePartner):

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
class ShardPartner(partners.BasePartner):

    type_name = 'shard->neighbour'

    def initiate(self, agent):
        if self.allocation_id is None:
            f = agent.allocate_resource(neighbours=1)
            f.add_callback(self._store_alloc_id)
            return f

    def _store_alloc_id(self, alloc):
        assert isinstance(alloc, resource.Allocation)
        self.allocation_id = alloc and alloc.id

    def on_goodbye(self, agent):
        f = partners.BasePartner.on_goodbye(self, agent)
        f.add_both(fiber.drop_result, agent.become_king)
        f.add_both(fiber.drop_result, agent.look_for_neighbours)
        return f


class Partners(partners.Partners):

    partners.has_many('hosts', 'host_agent', HostPartner)
    partners.has_many('neighbours', 'shard_agent', ShardPartner)


class ShardAgentRole(enum.Enum):
    '''
    king - a shard being the entry point (lobby binding)
    peasant - normal shard
    '''
    (king, peasant, ) = range(2)


@agent.register('shard_agent')
class ShardAgent(agent.BaseAgent, rpc.AgentMixin):

    partners_class = Partners

    @replay.mutable
    def initiate(self, state, hosts=10, neighbours=3):
        agent.BaseAgent.initiate(self)
        rpc.AgentMixin.initiate(self)

        state.resources.define('hosts', hosts)
        state.resources.define('neighbours', neighbours)

        # state.join_interest =\
        #     state.medium.register_interest(JoinShardContractor)
        # state.join_interest.bind_to_lobby()
        state.neighbour_interest =\
            state.medium.register_interest(
            contractor.Service(FindNeighboursContractor))
        state.medium.register_interest(FindNeighboursContractor)
        state.role = None
        self.become_king()

        return self.initiate_partners()

    @manhole.expose()
    @replay.journaled
    def look_for_neighbours(self, state):
        f = self.discover_service(FindNeighboursManager, timeout=1)
        f.add_callback(
            lambda recp: self.initiate_protocol(FindNeighboursManager, recp))
        f.add_callback(FindNeighboursManager.notify_finish)
        f.add_errback(self.look_for_failed)
        return f

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
        f.add_callback(fiber.drop_result, self.call_remote, to_divorce,
                       'check_your_role')
        f.add_callback(fiber.drop_result, self.substitute_partner,
                       to_divorce, to, alloc_ids[1])
        f.add_errback(self._mind_double_partnership, to, alloc_ids[1])
        f.add_callback(fiber.drop_result, self.become_peasant)
        return f

    def _mind_double_partnership(self, fail, recp, alloc_id):
        if fail.check(partners.DoublePartnership):
            return self.call_remote(recp, 'release_resource', alloc_id)
        else:
            fail.raiseException()

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
            state.role = ShardAgentRole.king

    @replay.mutable
    def become_peasant(self, state):
        if not self.is_peasant():
            state.neighbour_interest.unbind_from_lobby()
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

    @replay.mutable
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

    @replay.mutable
    def granted(self, state, grant):
        recp = grant.payload['joining_agent']
        if grant.payload['solution_type'] == SolutionType.join:
            f = state.agent.confirm_allocation(state.allocation_id)
            f.add_callback(fiber.drop_result,
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
        state.medium._error_handler(failure)
        msg = message.Cancellation(reason=str(failure.value))
        state.medium.defect(msg)
        return self._release_allocation()

    @replay.immutable
    def _finalize(self, state, _):
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

    @replay.journaled
    def initiate(self, state):
        msg = message.Announcement()
        msg.payload['joining_agent'] = state.agent.get_own_address()
        state.medium.announce(msg)
        state.allocations = list()

    @replay.journaled
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
        f.add_callback(fiber.drop_result, self._allocate_slots, slots_needed)
        f.add_callback(fiber.drop_result, self._prepare_grants, to_grant)
        f.add_callback(state.medium.grant)
        return f

    @replay.journaled
    def completed(self, state, reports):
        pass

    @replay.mutable
    def _release_unused_allocations(self, state, *_):
        # FIXME: possible n HTTP requests
        f = fiber.succeed()
        for alloc_id in state.allocations:
            if not state.agent.allocation_used(alloc_id):
                f.add_callback(fiber.drop_result,
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
            f.add_callback(fiber.drop_result,
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



# @serialization.register
# class JoinShardContractor(contractor.BaseContractor):

#     protocol_id = 'join-shard'
#     interest_type = InterestType.public

#     @replay.mutable
#     def announced(self, state, announcement):
#         state.nested_manager = None
#         our_action = None

#         def wants(a_type):
#             return a_type in announcement.payload['solutions']

#         wants_join = wants(shard.ActionType.join)
#         wants_create = wants(shard.ActionType.create)
#         wants_adopt = wants(shard.ActionType.adopt)

#         if wants_join:
#             allocation = state.agent.preallocate_resource(hosts=1)
#             if allocation:
#                 our_action = shard.ActionType.join
#                 cost = 0
#         if our_action is None and (wants_adopt or wants_create):
#             allocation = state.agent.preallocate_resource(children=1)
#             if allocation:
#                 our_action = wants_create and shard.ActionType.create or\
#                                               shard.ActionType.adopt
#                 cost = 20
#         state.preallocation_id = allocation and allocation.id

#         # create a bid for our own action
#         bid = None
#         if our_action is not None:
#             bid = message.Bid()
#             bid.payload['action_type'] = our_action
#             cost += announcement.payload['level'] * 15
#             bid.payload['cost'] = cost

#         f = fiber.Fiber()
#         if our_action in [shard.ActionType.create, None]:
#             # Maybe children shards can just join
#             # this poor fellow, lets ask them.
#             f.add_callback(fiber.drop_result, self._fetch_children_bids,
#                            announcement)
#         f.add_callback(self._pick_best_bid, bid)
#         f.add_callback(self._bid_refuse_or_handover, bid)
#         f.add_callback(fiber.drop_result, self._terminate_nested_manager)
#         return f.succeed()

#     @replay.mutable
#     def _fetch_children_bids(self, state, announcement):
#         children = state.agent.query_partners('children')
#         if len(children) == 0:
#             return list()

#         new_announcement = announcement.clone()
#         new_announcement.payload['level'] += 1

#         state.nested_manager = state.agent.initiate_protocol(
#             NestedJoinShardManager, children, new_announcement)
#         f = fiber.Fiber()
#         f.add_callback(fiber.drop_result,
#                        state.nested_manager.wait_for_bids)
#         return f.succeed()

#     @replay.immutable
#     def _terminate_nested_manager(self, state):
#         if state.nested_manager:
#             state.nested_manager.terminate()

#     @replay.immutable
#     def _pick_best_bid(self, state, nested_bids, own_bid):
#         # prepare the list of bids
#         bids = list()
#         if own_bid:
#             bids.append(own_bid)
#         if nested_bids is None:
#             nested_bids = list()
#         bids += nested_bids
#         self.log('_pick_best_bid analizes total of %d bids', len(bids))

#         # check if we have received anything
#         if len(bids) == 0:
#             self.info('Did not receive any bids to evaluate! '
#                       'Contract will fail.')
#             return None

#         # elect best bid
#         best = message.Bid.pick_best(bids)[0]

#         # Send refusals to contractors of nested manager which we already
#         # know will not receive the grant.
#         for bid in bids:
#             if bid == best:
#                 continue
#             elif bid in nested_bids:
#                 state.nested_manager.reject_bid(bid)
#         return best

#     @replay.journaled
#     def _bid_refuse_or_handover(self, state, bid=None, original_bid=None):
#         if bid is None:
#             refusal = message.Refusal()
#             return state.medium.refuse(refusal)
#         elif bid == original_bid:
#             state.bid = bid
#             return state.medium.bid(bid)
#         else:
#             f = fiber.Fiber()
#             f.add_callback(self.release_preallocation)
#             f.add_callback(fiber.drop_result, state.medium.handover, bid)
#             return f.succeed()

#     @replay.immutable
#     def release_preallocation(self, state, *_):
#         if state.preallocation_id is not None:
#             return state.agent.release_resource(state.preallocation_id)

#     announce_expired = release_preallocation
#     rejected = release_preallocation
#     expired = release_preallocation

#     @replay.mutable
#     def granted(self, state, grant):
#         joining_agent_id = grant.payload['joining_agent'].key

#         if state.bid.payload['action_type'] == shard.ActionType.create:
#             f = fiber.Fiber()
#             f.add_callback(state.agent.confirm_allocation)
#             f.add_callback(fiber.drop_result,
#                            state.agent.prepare_child_descriptor)
#             f.add_callback(self._request_start_agent)
#             f.add_callback(state.agent.establish_partnership,
#                            state.preallocation_id, u'child', u'parent')
#             f.add_callback(self._generate_new_address, joining_agent_id)
#             f.add_callback(state.medium.update_manager_address)
#             f.add_callbacks(self._finalize, self._granted_failed)
#             return f.succeed(state.preallocation_id)
#         elif state.bid.payload['action_type'] == shard.ActionType.join:
#             f = fiber.Fiber()
#             f.add_callback(state.agent.confirm_allocation)
#             f.add_callback(
#                 fiber.drop_result, state.agent.establish_partnership,
#                 grant.payload['joining_agent'], state.preallocation_id)
#             f.add_callback(state.medium.update_manager_address)
#             f.add_callbacks(self._finalize, self._granted_failed)
#             return f.succeed(state.preallocation_id)
#         elif state.bid.payload['action_type'] == shard.ActionType.adopt:
#             f = fiber.Fiber()
#             f.add_callback(state.agent.confirm_allocation)
#             f.add_callback(
#                 fiber.drop_result, state.agent.establish_partnership,
#                 grant.payload['joining_agent'], state.preallocation_id,
#                 u'child', u'parent')
#             f.add_callbacks(self._finalize, self._granted_failed)
#             return f.succeed(state.preallocation_id)

#     def _granted_failed(self, failure):
#         self.release_preallocation()
#         failure.raiseException()

#     @replay.immutable
#     def _finalize(self, state, _):
#         report = message.FinalReport()
#         state.medium.finalize(report)

#     @replay.immutable
#     def _request_start_agent(self, state, desc):
#         recp = state.medium.announce.payload['joining_agent']
#         totals, _ = state.agent.list_resource()
#         return host.start_agent(state.agent, recp, desc, allocation_id=None,
#                                 **totals)

#     def _generate_new_address(self, shard_partner, agent_id):
#         return recipient.Agent(agent_id, shard_partner.recipient.shard)


# @serialization.register
# class NestedJoinShardManager(manager.BaseManager):

#     protocol_id = 'join-shard'

#     @replay.journaled
#     def initiate(self, state, announcement):
#         state.medium.announce(announcement)

#     @replay.immutable
#     def wait_for_bids(self, state):
#         f = fiber.Fiber()
#         f.add_callback(state.medium.wait_for_state)
#         f.add_callback(lambda _: state.medium.contractors.keys())
#         f.succeed(ContractState.closed)
#         return f

#     @replay.journaled
#     def reject_bid(self, state, bid):
#         self.debug('Sending rejection to bid from nested manager.')
#         return state.medium.reject(bid)

#     @replay.journaled
#     def terminate(self, state):
#         state.medium.terminate()


@descriptor.register("shard_agent")
class Descriptor(descriptor.Descriptor):
    pass
