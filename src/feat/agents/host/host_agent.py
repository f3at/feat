# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import socket
import operator

from feat.agents.base import (agent, contractor, recipient, message,
                              replay, descriptor, replier,
                              partners, resource, document, notifier,
                              problem, task, )
from feat.agents.common import rpc, monitor
from feat.agents.common import shard as common_shard
from feat.agents.common.host import check_categories, Descriptor
from feat.agents.host import port_allocator
from feat.interface.protocols import InterestType
from feat.common import fiber, manhole, serialization
from feat.agencies.interface import NotFoundError
from feat.interface.agent import Access, Address, Storage, CategoryError

DEFAULT_RESOURCES = {"host": 1,
                     "bandwidth": 100,
                     "epu": 500,
                     "core": 2,
                     "mem": 1000}


DEFAULT_CATEGORIES = {'access': Access.none,
                      'address': Address.none,
                      'storage': Storage.none}


@serialization.register
class HostedPartner(agent.BasePartner):
    '''
    This class is for agents we are partners with only because we started them.
    If your patnership is meant to represent sth more you should implement the
    appriopriate handler.
    '''

    type_name = 'host->agent'

    def on_restarted(self, agent):
        agent.call_next(agent.check_if_agency_hosts, self.recipient)


@serialization.register
class ShardPartner(agent.BasePartner):

    type_name = 'host->shard'

    def initiate(self, agent):
        f = agent.switch_shard(self.recipient.shard)
        f.add_callback(fiber.drop_param, agent.callback_event,
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

    def on_died(self, agent, brothers, monitor):
        agent.info('Shard partner died.')
        recipients = map(operator.attrgetter('recipient'), brothers)
        task = agent.collectively_restart_shard(
            recipients, self.recipient.key, monitor)
        return partners.accept_responsability(task)

    def on_restarted(self, agent):
        agent.callback_event('shard_agent_restarted', self.recipient)


class Partners(agent.Partners):

    default_handler = HostedPartner

    partners.has_one('shard', 'shard_agent', ShardPartner)


@agent.register('host_agent')
class HostAgent(agent.BaseAgent, rpc.AgentMixin, notifier.AgentMixin,
                resource.AgentMixin):

    partners_class = Partners

    @replay.mutable
    def initiate(self, state, hostdef=None):
        state.medium.register_interest(StartAgentReplier)
        state.medium.register_interest(StartAgentContractor)
        state.medium.register_interest(
            contractor.Service(StartAgentContractor))
        state.medium.register_interest(HostAllocationContractor)
        state.medium.register_interest(
            problem.SolveProblemInterest(MissingShard))
        state.medium.register_interest(
            problem.SolveProblemInterest(RestartShard))
        ports = state.medium.get_descriptor().port_range
        state.port_allocator = port_allocator.PortAllocator(self, ports)

        f = fiber.Fiber()
        f.add_callback(fiber.drop_param, self._update_hostname)
        f.add_callback(fiber.drop_param, self._load_definition, hostdef)
        return f.succeed()

    @replay.journaled
    def startup(self, state):
        f = self.start_join_shard_manager()
        f.add_callback(fiber.drop_param, self.startup_monitoring)
        return f

    @replay.journaled
    def check_if_agency_hosts(self, state, recp):
        '''
        Called after partner has been restarted. It checks our agency
        is in charge of this agent. If not it removes the partnership.
        '''
        if not state.medium.check_if_hosted(recp.key):
            self.debug('Detected that agent with recp %r has moved to '
                       'different agency, we are breaking up.')
            return self.breakup(recp)

    @replay.journaled
    def start_join_shard_manager(self, state):
        f = fiber.succeed()
        if state.partners.shard is None:
            f.add_callback(fiber.drop_param, common_shard.start_manager, self)
            f.add_errback(fiber.drop_param, self.start_own_shard)
        return f

    @replay.journaled
    def start_own_shard(self, state, shard=None):
        f = common_shard.prepare_descriptor(self, shard)
        f.add_callback(self.start_agent)
        return f

    @replay.journaled
    def resolve_missing_shard_agent_problem(self, state, host_recipients):
        task = state.medium.initiate_protocol(
            problem.CollectiveSolver, MissingShard(self), host_recipients)
        return task.notify_finish()

    @replay.mutable
    def collectively_restart_shard(self, state, host_recipients,
                                   agent_id, monitor):
        task = getattr(state, 'restart_shard_task', None)
        if task is None or task.finished():
            state.restart_shard_task = state.medium.initiate_protocol(
                problem.CollectiveSolver,
                RestartShard(self, agent_id, monitor),
                host_recipients)
        return state.restart_shard_task

    @replay.mutable
    def wait_for_shard_restart(self, state):
        task = getattr(state, 'restart_shard_task', None)
        if task is None or task.finished():
            return fiber.succeed(state.partners.shard)
        else:
            return self.wait_for_event('shard_agent_restarted')

    @replay.immutable
    def get_shard_partner(self, state):
        partner = state.partners.shard
        self.log('In get_shard_partner(). Current result is: %r', partner)
        if partner:
            return fiber.succeed(partner)
        f = self.wait_for_event('joined_to_shard')
        f.add_callback(fiber.drop_param, self.get_shard_partner)
        return f

    @replay.journaled
    def switch_shard(self, state, shard):
        self.debug('Switching shard to %r', shard)
        desc = state.medium.get_descriptor()

        def save_change(desc, shard):
            desc.shard = shard

        f = fiber.Fiber()
        f.add_callback(fiber.drop_param, state.medium.leave_shard, desc.shard)
        f.add_callback(fiber.drop_param, self.update_descriptor,
                       save_change, shard)
        f.add_callback(fiber.drop_param, state.medium.join_shard, shard)
        return f.succeed()

    @manhole.expose()
    @replay.journaled
    def start_agent(self, state, doc_id, allocation_id=None, **kwargs):
        task = self.initiate_protocol(StartAgent, doc_id, allocation_id,
                                      kwargs=kwargs)
        return task.notify_finish()

    @replay.immutable
    def medium_start_agent(self, state, desc, **kwargs):
        '''
        Just delegation to Agency part. Used by StartAgent task.
        '''
        return state.medium.start_agent(desc, **kwargs)

    @replay.journaled
    def restart_agent(self, state, agent_id):
        self.debug('I will restart agent with id %r.', agent_id)
        return self.start_agent(agent_id)

    @manhole.expose()
    @rpc.publish
    @replay.immutable
    def get_hostname(self, state):
        desc = state.medium.get_descriptor()
        return desc.hostname

    @manhole.expose()
    @rpc.publish
    @replay.side_effect
    def get_ip(self):
        return unicode(socket.gethostbyname(socket.gethostname()))

    @rpc.publish
    @replay.mutable
    def allocate_ports(self, state, number, group='misc'):
        try:
            return state.port_allocator.reserve_ports(number, group)
        except port_allocator.PortAllocationError as e:
            return fiber.fail(e)

    @rpc.publish
    @replay.mutable
    def release_ports(self, state, ports, group='misc'):
        return state.port_allocator.release_ports(ports, group)

    @rpc.publish
    @replay.mutable
    def set_ports_used(self, state, ports, group='misc'):
        return state.port_allocator.set_ports_used(ports, group)

    @rpc.publish
    @replay.immutable
    def get_num_free_ports(self, state, group='misc'):
        return state.port_allocator.num_free(group)

    @rpc.publish
    def premodify_allocation(self, allocation_id, **delta):
        return resource.AgentMixin.premodify_allocation(self,
                allocation_id, **delta)

    @rpc.publish
    def apply_modification(self, change_id):
        return resource.AgentMixin.apply_modification(self, change_id)

    @rpc.publish
    def release_modification(self, change_id):
        return resource.AgentMixin.release_modification(self, change_id)

    @manhole.expose()
    @rpc.publish
    def release_resource(self, alloc_id):
        return resource.AgentMixin.release_resource(self, alloc_id)

    ### Private Methods ###

    @replay.immutable
    def _discover_hostname(self, state):
        return state.medium.get_hostname()

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
                  ", ".join(["%s=%s" % (n, v.name)
                             for n, v in categories.iteritems()]))
        state.categories = categories

    @replay.immutable
    def check_requirements(self, state, doc):
        agnt = agent.registry_lookup(doc.document_type)
        ret = check_categories(self, agnt.categories)
        if not ret:
            msg = "Categoryies doesn't match"
            self.error(msg)
            raise CategoryError(msg)
        return doc


class StartAgent(task.BaseTask):

    timeout = 10
    protocol_id = "host_agent.start-agent"

    @replay.entry_point
    def initiate(self, state, doc_id, allocation_id, kwargs=dict()):
        if isinstance(doc_id, descriptor.Descriptor):
            doc_id = doc_id.doc_id
        assert isinstance(doc_id, (str, unicode, ))

        state.doc_id = doc_id
        state.descriptor = None
        state.allocation_id = allocation_id

        f = fiber.succeed()
        f.add_callback(fiber.drop_param, self._fetch_descriptor)
        f.add_callback(fiber.drop_param, self._check_requirements)
        f.add_callback(fiber.drop_param, self._update_shard_field)
        f.add_callback(fiber.drop_param, self._validate_allocation)
        f.add_callback(fiber.drop_param, getattr, state, 'descriptor')
        f.add_callback(state.agent.medium_start_agent, **kwargs)
        f.add_callback(recipient.IRecipient)
        f.add_callback(self._establish_partnership)
        return f

    @replay.immutable
    def _establish_partnership(self, state, recp):
        f = state.agent.establish_partnership(
            recp, state.allocation_id, our_role=u'host', allow_double=True)
        return f

    @replay.mutable
    def _fetch_descriptor(self, state):
        f = state.agent.get_document(state.doc_id)
        f.add_callback(self._store_descriptor)
        return f

    @replay.mutable
    def _store_descriptor(self, state, value):
        state.descriptor = value

    @replay.mutable
    def _check_requirements(self, state):
        state.agent.check_requirements(state.descriptor)

    @replay.mutable
    def _update_shard_field(self, state):
        '''Sometime creating the descriptor for new agent we cannot know in
        which shard it will endup. If it is None or set to lobby, the HA
        will update the field to match his own'''
        if state.descriptor.shard is None or state.descriptor.shard == 'lobby':
            own_shard = state.agent.get_own_address().shard
            state.descriptor.shard = own_shard
        f = fiber.succeed(state.descriptor)
        f.add_callback(state.agent.save_document)
        f.add_callback(self._store_descriptor)
        return f

    @replay.mutable
    def _validate_allocation(self, state):
        if state.allocation_id:
            return state.agent.check_allocation_exists(state.allocation_id)
        else:
            resources = self._get_factory().resources
            f = state.agent.allocate_resource(**resources)
            f.add_callback(self._store_allocation)
            return f

    @replay.mutable
    def _store_allocation(self, state, allocation):
        state.allocation_id = allocation.id

    @replay.immutable
    def _get_factory(self, state):
        return agent.registry_lookup(state.descriptor.document_type)


@serialization.register
class MissingShard(problem.BaseProblem):

    problem_id = 'missing-shard'

    def wait_for_solution(self):
        return self.agent.get_shard_partner()

    def solve_for(self, solution, recp):
        return self.agent.call_remote(solution, 'propose_to', recp)

    def solve_localy(self):
        own_address = self.agent.get_own_address()
        return self.agent.start_own_shard(own_address.shard)


@serialization.register
class RestartShard(problem.BaseProblem):

    problem_id = 'restart-shard'

    def __init__(self, agent, agent_id=None, monitor=None):
        problem.BaseProblem.__init__(self, agent)
        self.agent_id = agent_id
        self.monitor = monitor

    def wait_for_solution(self):
        return self.agent.wait_for_shard_restart()

    def solve_for(self, solution, recp):
        pass

    def solve_localy(self):
        partner = self.agent.query_partners('shard')
        f = fiber.succeed()
        if partner:
            f.add_callback(fiber.drop_param, self.agent.remove_partner,
                           partner)
        f.add_callback(fiber.drop_param, self._cleanup_partners)
        f.add_callback(fiber.drop_param, self.agent.restart_agent,
                       self.agent_id)
        f.add_callback(self._finalize)
        return f

    def _cleanup_partners(self):
        f = self.agent.get_document(self.agent_id)
        f.add_callback(self._do_remove_partners)
        return f

    def _do_remove_partners(self, desc):
        # remove from the shard agents descriptor the partnership to ourselves
        # and/or to the old agent who was hosting him
        own = self.agent.get_own_address()
        filtered_partners = list()
        for partner in desc.partners:
            if partner.recipient == own or partner.role == 'host':
                desc.allocations.pop(partner.allocation_id, None)
            else:
                filtered_partners.append(partner)
        desc.partners = filtered_partners
        return self.agent.save_document(desc)

    def _finalize(self, recp):
        self.agent.callback_event('shard_agent_restarted', recp)
        return monitor.notify_restart_complete(self.agent, self.monitor, recp)


class HostAllocationContractor(contractor.BaseContractor):

    protocol_id = 'allocate-resources'
    interest_type = InterestType.private
    concurrency = 1

    @replay.entry_point
    def announced(self, state, announcement):
        categories = announcement.payload['categories']
        ret = check_categories(state.agent, categories)
        if not ret:
            self._refuse("Categories doesn't match")
            return

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

        bid = self._get_cost(bid)
        state.medium.bid(bid)

    @replay.immutable
    def _refuse(self, state, reason):
        state.medium.refuse(message.Refusal(payload=reason))

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
        f.add_callbacks(self._finalize, self._granted_failed)
        return f.succeed(state.preallocation_id)

    ### Private ###

    @replay.mutable
    def _granted_failed(self, state, fail):
        msg = "Granted failed with failure %r" % (fail, )
        cancel = message.Cancellation(reason=msg)
        state.medium.defect(cancel)
        self.error(msg)
        return self.release_preallocation()

    @replay.mutable
    def _finalize(self, state, allocation):
        report = message.FinalReport()
        report.payload['allocation_id'] = allocation.id
        state.medium.finalize(report)

    @replay.immutable
    def _get_cost(self, state, bid):
        bid.payload['cost'] = 0
        return bid

class StartAgentReplier(replier.BaseReplier):

    protocol_id = 'start-agent'

    @replay.entry_point
    def requested(self, state, request):
        a_id = request.payload['allocation_id']
        args = request.payload['args']
        kwargs = request.payload['kwargs']
        doc_id = request.payload['doc_id']

        f = fiber.Fiber()
        f.add_callback(fiber.drop_param, state.agent.start_agent, doc_id,
                       a_id, *args, **kwargs)
        f.add_callback(self._send_reply)
        f.succeed(doc_id)
        return f

    @replay.mutable
    def _send_reply(self, state, new_agent):
        msg = message.ResponseMessage()
        msg.payload['agent'] = recipient.IRecipient(new_agent)
        state.medium.reply(msg)


class StartAgentContractor(contractor.BaseContractor):

    protocol_id = 'start-agent'

    @replay.entry_point
    def announced(self, state, announce):
        state.descriptor = announce.payload['descriptor']
        state.factory = agent.registry_lookup(state.descriptor.document_type)

        if not check_categories(state.agent, state.factory.categories):
            self._refuse()
            return

        alloc = state.agent.preallocate_resource(
            **state.factory.resources)

        if alloc is None:
            self._refuse()
            return

        state.alloc_id = alloc.id

        bid = message.Bid()
        state.medium.bid(bid)

    @replay.mutable
    def _release_allocation(self, state, *_):
        if state.alloc_id:
            return state.agent.release_resource(state.alloc_id)

    closed = _release_allocation
    rejected = _release_allocation
    expired = _release_allocation
    cancelled = _release_allocation

    @replay.entry_point
    def granted(self, state, grant):
        f = state.agent.confirm_allocation(state.alloc_id)
        f.add_callback(fiber.drop_param, state.agent.start_agent,
                       state.descriptor.doc_id, state.alloc_id)
        f.add_callbacks(self._finalize, self._starting_failed)
        return f

    @replay.immutable
    def _finalize(self, state, recp):
        msg = message.FinalReport(payload=recp)
        state.medium.finalize(msg)

    @replay.immutable
    def _starting_failed(self, state, fail):
        msg = message.Cancellation(reason=fail)
        f = self._release_allocation()
        f.add_callback(fiber.drop_param, state.medium.defect,
                       msg)
        return f

    @replay.immutable
    def _refuse(self, state):
        msg = message.Refusal()
        state.medium.refuse(msg)
