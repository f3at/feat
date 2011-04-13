# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import socket
import operator

from feat.agents.base import (agent, contractor, recipient, message,
                              replay, descriptor, replier,
                              partners, resource, document, notifier,
                              problem, )
from feat.agents.common import rpc
from feat.agents.common import shard as common_shard
from feat.agents.host import port_allocator
from feat.interface.protocols import InterestType
from feat.common import fiber, manhole, serialization
from feat.agencies.interface import NotFoundError
from feat.interface.agent import Access, Address, Storage, CategoryError

DEFAULT_RESOURCES = {"host": 1,
                     "epu": 500,
                     "core": 2,
                     "mem": 1000}


DEFAULT_CATEGORIES = {'access': Access.none,
                      'address': Address.none,
                      'storage': Storage.none}


@serialization.register
class ShardPartner(partners.BasePartner):

    type_name = 'host->shard'

    def initiate(self, agent):
        f = agent.switch_shard(self.recipient.shard)
        f.add_callback(fiber.drop_result, agent.callback_event,
                       'joined_to_shard', None)
        return f

    def on_goodbye(self, agent, brothers):
        '''
        Algorithm for resolving this situation goes as follows.
        We receive the list of brothers (HostPartner currently in same
        comporomising position). The algorithm always picks the first from the
        list as the one to resolve the problem. Everybody else needs to
        ask his lefthand neighbour to resolve a situation for him.
        If the requests to the neighbour timeouts, he is removed from the
        local list and the algorithm iterates in.
        '''
        agent.info('Shard partner said goodbye.')
        recipients = map(operator.attrgetter('recipient'), brothers)
        return agent.resolve_missing_shard_agent_problem(recipients)


class Partners(partners.Partners):

    partners.has_one('shard', 'shard_agent', ShardPartner)


@agent.register('host_agent')
class HostAgent(agent.BaseAgent, rpc.AgentMixin, notifier.AgentMixin):

    partners_class = Partners

    @replay.journaled
    def resolve_missing_shard_agent_problem(self, state, host_recipients):
        f = fiber.succeed()
        f.add_callback(fiber.drop_result, state.medium.initiate_task,
                       problem.CollectiveSolver, MissingShard(self),
                       host_recipients)
        f.add_callback(lambda x: x.notify_finish())
        return f

    @replay.immutable
    def get_shard_partner(self, state):
        partner = state.partners.shard
        self.log('In get_shard_partner(). Current result is: %r', partner)
        if partner:
            return fiber.succeed(partner)
        f = self.wait_for_event('joined_to_shard')
        f.add_callback(fiber.drop_result, self.get_shard_partner)
        return f

    @replay.entry_point
    def initiate(self, state, hostdef=None):
        agent.BaseAgent.initiate(self)
        rpc.AgentMixin.initiate(self)
        notifier.AgentMixin.initiate(self, state)

        state.medium.register_interest(StartAgentReplier)
        state.medium.register_interest(ResourcesAllocationContractor)
        state.medium.register_interest(
            problem.SolveProblemInterest(MissingShard(self)))
        ports = state.medium.get_descriptor().port_range
        state.port_allocator = port_allocator.PortAllocator(self, ports)

        f = fiber.Fiber()
        f.add_callback(fiber.drop_result, self._update_hostname)
        f.add_callback(fiber.drop_result, self._load_definition, hostdef)
        f.add_callback(fiber.drop_result, self.initiate_partners)
        return f.succeed()

    @replay.journaled
    def startup(self, state):
        return self.start_join_shard_manager()

    @replay.journaled
    def start_join_shard_manager(self, state):
        if state.partners.shard is None:
            f = common_shard.start_manager(self)
            f.add_errback(fiber.drop_result, self.start_own_shard)
            return f

    @replay.journaled
    def start_own_shard(self, state, shard=None):
        f = common_shard.prepare_descriptor(self, shard)
        f.add_callback(self.start_agent)
        return f

    @replay.journaled
    def switch_shard(self, state, shard):
        self.debug('Switching shard to %r', shard)
        desc = state.medium.get_descriptor()

        def save_change(desc, shard):
            desc.shard = shard

        f = fiber.Fiber()
        f.add_callback(fiber.drop_result, state.medium.leave_shard, desc.shard)
        f.add_callback(fiber.drop_result, self.update_descriptor,
                       save_change, shard)
        f.add_callback(fiber.drop_result, state.medium.join_shard, shard)
        return f.succeed()

    @manhole.expose()
    @replay.journaled
    def start_agent(self, state, doc_id, allocation_id=None, *args, **kwargs):
        if isinstance(doc_id, descriptor.Descriptor):
            doc_id = doc_id.doc_id
        assert isinstance(doc_id, (str, unicode, ))

        f = fiber.succeed()
        if allocation_id:
            f.add_callback(fiber.drop_result,
                           self.check_allocation_exists, allocation_id)
        f.add_callback(fiber.drop_result, self.get_document, doc_id)
        f.add_callback(self._check_requeriments)
        f.add_callback(self._update_shard_field)
        f.add_callback(state.medium.start_agent, *args, **kwargs)
        f.add_callback(recipient.IRecipient)
        f.add_callback(self.establish_partnership, allocation_id,
                       our_role=u'host')
        return f

    @manhole.expose()
    @replay.journaled
    def start_agent_from_descriptor(self, state, desc):
        return self.start_agent(desc.doc_id)

    @replay.immutable
    def _update_shard_field(self, state, desc):
        '''Sometime creating the descriptor for new agent we cannot know in
        which shard it will endup. If it is None or set to lobby, the HA
        will update the field to match his own'''
        if desc.shard is None or desc.shard == 'lobby':
            desc.shard = self.get_own_address().shard
        f = fiber.Fiber()
        f.add_callback(state.medium.save_document)
        return f.succeed(desc)

    @manhole.expose()
    @rpc.publish
    @replay.immutable
    def get_hostname(self, state):
        desc = state.medium.get_descriptor()
        return desc.hostname

    @rpc.publish
    @replay.mutable
    def allocate_ports(self, state, number):
        try:
            return state.port_allocator.reserve_ports(number)
        except port_allocator.PortAllocationError as e:
            return fiber.fail(e)

    @rpc.publish
    @replay.mutable
    def release_ports(self, state, ports):
        return state.port_allocator.release_ports(ports)

    @rpc.publish
    @replay.mutable
    def set_ports_used(self, state, ports):
        return state.port_allocator.set_ports_used(ports)

    @rpc.publish
    @replay.immutable
    def get_num_free_ports(self, state):
        return state.port_allocator.num_free()

    ### Private Methods ###

    @replay.side_effect
    def _discover_hostname(self):
        return unicode(socket.gethostbyaddr(socket.gethostname())[0])

    @agent.update_descriptor
    def _update_hostname(self, state, desc, hostname=None):
        if not hostname:
            hostname = self._discover_hostname()
        desc.hostname = hostname

    @replay.immutable
    def _load_definition(self, state, hostdef=None):
        if not hostdef:
            return self._apply_defaults()

        if isinstance(hostdef, document.Document):
            return self._apply_definition(hostdef)

        f = fiber.Fiber()
        f.add_callback(state.medium.get_document)
        f.add_callbacks(self._apply_definition, self._definition_not_found,
                        ebargs=(hostdef, ))
        return f.succeed(hostdef)

    def _definition_not_found(self, failure, hostdef_id):
        failure.trap(NotFoundError)
        msg = "Host definition document %r not found" % hostdef_id
        self.error(msg)
        raise NotFoundError(msg)

    def _apply_definition(self, hostdef):
        self._setup_resources(hostdef.resources)
        self._setup_categories(hostdef.categories)

    def _apply_defaults(self):
        self._setup_resources(DEFAULT_RESOURCES)
        self._setup_categories(DEFAULT_CATEGORIES)

    @replay.mutable
    def _setup_resources(self, state, resources):
        if not resources:
            self.warning("Host do not have any resources defined")
            return

        self.info("Setting host resources to: %s",
                  ", ".join(["%s=%s" % (n, v)
                             for n, v in resources.iteritems()]))

        for name, total in resources.iteritems():
            state.resources.define(name, total)

    @replay.mutable
    def _setup_categories(self, state, categories):
        if not categories:
            self.warning("Host do not have any categories defined")
            return

        self.info("Setting host categories to: %s",
                  ", ".join(["%s=%s" % (n, v)
                             for n, v in categories.iteritems()]))

        state.categories = categories

    @replay.immutable
    def _check_requeriments(self, state, doc):
        agnt = agent.registry_lookup(doc.document_type)
        agent_categories = agnt.categories
        for cat, val in agent_categories.iteritems():
            if ((isinstance(val, Access) and val == Access.none) or
               (isinstance(val, Address) and val == Address.none) or
               (isinstance(val, Storage) and val == Storage.none)):
                continue

            if not (cat in state.categories and
                    state.categories[cat] == val):
                msg = "Category %s doesn't match %s != %s" % (
                      cat, val, state.categories[cat])
                self.error(msg)
                raise CategoryError(msg)
        return doc


@serialization.register
class MissingShard(problem.BaseProblem):

    def wait_for_solution(self):
        return self.agent.get_shard_partner()

    def solve_for(self, solution, recp):
        return self.agent.call_remote(solution, 'propose_to', recp)

    def solve_localy(self):
        own_address = self.agent.get_own_address()
        return self.agent.start_own_shard(own_address.shard)


class ResourcesAllocationContractor(contractor.BaseContractor):
    protocol_id = 'allocate-resources'
    interest_type = InterestType.public

    @replay.entry_point
    def announced(self, state, announcement):
        resources = announcement.payload['resources']
        try:
            preallocation = state.agent.preallocate_resource(**resources)
        except resource.UnknownResource:
            self._refuse("Unknown resource! WTF?")
            return

        if preallocation is None:
            self._refuse("Not enough resource")
            return

        state.preallocation_id = preallocation.id
        # Create a bid
        bid = message.Bid()
        bid.payload['allocation_id'] = state.preallocation_id

        f = fiber.Fiber()
        f.add_callback(self._get_cost)
        f.add_callback(state.medium.bid)
        return f.succeed(bid)

    @replay.immutable
    def _refuse(self, state, reason):
        state.medium.refuse(message.Refusal(payload=reason))

    @replay.immutable
    def _get_cost(self, state, bid):
        bid.payload['cost'] = 0
        return bid

    @replay.mutable
    def release_preallocation(self, state, *_):
        if state.preallocation_id is not None:
            return state.agent.release_resource(state.preallocation_id)

    announce_expired = release_preallocation
    rejected = release_preallocation
    expired = release_preallocation

    @replay.entry_point
    def granted(self, state, grant):
        f = fiber.Fiber()
        f.add_callback(state.agent.confirm_allocation)
        f.add_callback(self._finalize)
        return f.succeed(state.preallocation_id)

    @replay.mutable
    def _finalize(self, state, allocation):
        report = message.FinalReport()
        report.payload['allocation_id'] = allocation.id
        state.medium.finalize(report)


@descriptor.register("host_agent")
class Descriptor(descriptor.Descriptor):

    # Hostname of the machine, updated when an agent is started
    document.field('hostname', None)
    # Range used for allocating new ports
    document.field('port_range', (5000, 5999, ))


class StartAgentReplier(replier.BaseReplier):

    protocol_id = 'start-agent'

    @replay.entry_point
    def requested(self, state, request):
        a_id = request.payload['allocation_id']
        args = request.payload['args']
        kwargs = request.payload['kwargs']
        doc_id = request.payload['doc_id']

        f = fiber.Fiber()
        f.add_callback(fiber.drop_result, state.agent.start_agent, doc_id,
                       a_id, *args, **kwargs)
        f.add_callback(self._send_reply)
        f.succeed(doc_id)
        return f

    @replay.mutable
    def _send_reply(self, state, new_agent):
        msg = message.ResponseMessage()
        msg.payload['agent'] = recipient.IRecipient(new_agent)
        state.medium.reply(msg)
