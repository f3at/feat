# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import types

from twisted.python.failure import Failure
from zope.interface import implements

from feat.common import (log, decorator, serialization, fiber, defer,
                         manhole, mro, )
from feat.interface import generic, agent, protocols
from feat.agencies import retrying
from feat.agents.base import (recipient, replay, requester,
                              replier, partners, dependency, manager, )
from feat.agents.common import monitor, rpc, export

from feat.interface.agent import *
from feat.interface.agency import *


registry = dict()


@decorator.parametrized_class
def register(klass, name, configuration_id=None):
    global registry
    registry[name] = klass
    doc_id = configuration_id or name + "_conf"
    klass.descriptor_type = name
    klass.type_name = name + ":data"
    klass.configuration_doc_id = doc_id
    serialization.register(klass)
    return klass


def registry_lookup(name):
    global registry
    return registry.get(name, None)


@decorator.simple_function
def update_descriptor(function):

    @replay.immutable
    def decorated(self, state, *args, **kwargs):
        immfun = replay.immutable(function)
        method = types.MethodType(immfun, self, self.__class__)
        f = fiber.succeed(method)
        f.add_callback(state.medium.update_descriptor, *args, **kwargs)
        return f

    return decorated


@serialization.register
class BasePartner(partners.BasePartner):
    pass


@serialization.register
class MonitorPartner(monitor.PartnerMixin, BasePartner):

    type_name = "agent->monitor"


@serialization.register
class HostPartner(BasePartner):

    type_name = "agent->host"

#FIXME: At some point we should enable this code.
#       host.SpecialHostPartnerMixin would have to be merged with base agent
#       to prevent newly restarted agents to commit suicide and test would
#       have to be fixed (good luck).
#
#    def on_buried(self, agent, brothers=None):
#        if self.role == u"host":
#            agent.info("Host agent %s died, %s committing suicide",
#                       self.recipient.key, agent.get_full_id())
#            agent.terminate_hard()


class Partners(partners.Partners):

    partners.has_many("monitors", "monitor_agent", MonitorPartner)
    partners.has_many("hosts", "host_agent", HostPartner)


class MetaAgent(type(replay.Replayable), type(manhole.Manhole)):
    implements(agent.IAgentFactory)


class BaseAgent(mro.MroMixin, log.Logger, log.LogProxy, replay.Replayable,
                manhole.Manhole, rpc.AgentMixin, export.AgentMigrationBase,
                dependency.AgentDependencyMixin, monitor.AgentMixin):

    __metaclass__ = MetaAgent

    implements(agent.IAgent, generic.ITimeProvider)

    partners_class = Partners

    standalone = False

    categories = {'access': agent.Access.none,
                  'address': agent.Address.none,
                  'storage': agent.Storage.none}

    # resources required to run the agent
    resources = {'epu': 1}

    def __init__(self, medium):
        manhole.Manhole.__init__(self)
        log.Logger.__init__(self, medium)
        log.LogProxy.__init__(self, medium)
        replay.Replayable.__init__(self, medium)

    @replay.immutable
    def restored(self, state):
        log.Logger.__init__(self, state.medium)
        log.LogProxy.__init__(self, state.medium)
        replay.Replayable.restored(self)

    def init_state(self, state, medium):
        state.medium = agent.IAgencyAgent(medium)
        state.partners = self.partners_class(self)

    @replay.immutable
    def get_status(self, state):
        return state.medium.state

    ### IAgent Methods ###

    @replay.journaled
    def initiate_agent(self, state, **keywords):
        f = self.call_mro('initiate', **keywords)
        f.add_callback(fiber.drop_param, self._initiate_partners)
        return f

    @replay.journaled
    def startup_agent(self, state):
        return self.call_mro('startup')

    @replay.journaled
    def shutdown_agent(self, state):
        return self.call_mro('shutdown')

    @replay.journaled
    def on_agent_killed(self, state):
        return self.call_mro('on_killed')

    @replay.journaled
    def on_agent_disconnect(self, state):
        return self.call_mro('on_disconnect')

    @replay.journaled
    def on_agent_reconnect(self, state):
        return self.call_mro('on_reconnect')

    ### Methods called as a result of agency calls ###

    @replay.immutable
    def initiate(self, state):
        state.medium.register_interest(replier.Ping)

    @replay.journaled
    def shutdown(self, state):
        desc = self.get_descriptor()
        self.info('Agent shutdown, partners: %r', desc.partners)
        fibers = [x.call_mro('on_shutdown', agent=self)
                   for x in desc.partners]
        f = fiber.FiberList(fibers)
        return f.succeed()

    def startup(self):
        pass

    def on_killed(self):
        pass

    def on_disconnect(self):
        pass

    def on_reconnect(self):
        pass

    ### Public methods ###

    @replay.immutable
    def get_descriptor(self, state):
        '''Returns a copy of the agent descriptos.'''
        return state.medium.get_descriptor()

    @replay.immutable
    def get_configuration(self, state):
        '''Returns a copy of the agent config.'''
        return state.medium.get_configuration()

    @replay.immutable
    def get_agent_id(self, state):
        '''Returns a global unique identifier for the agent.
        Do not change when the agent is restarted.'''
        desc = state.medium.get_descriptor()
        return desc.doc_id

    @replay.immutable
    def get_instance_id(self, state):
        """Returns the agent instance identifier.
        Changes when the agent is restarted.
        It's unique only for the agent."""
        desc = state.medium.get_descriptor()
        return desc.instance_id

    @replay.immutable
    def get_full_id(self, state):
        """Return a global unique identifier for this agent instance.
        It's a combination of agent_id and instance_id:
          full_id = agent_id + '/' + instance_id
        """
        desc = state.medium.get_descriptor()
        return desc.doc_id + u"/" + unicode(desc.instance_id)

    def get_cmd_line(self, *args, **kwargs):
        raise NotImplemented('To be used for standalone agents!')

    ### ITimeProvider Methods ###

    @replay.immutable
    def get_time(self, state):
        return generic.ITimeProvider(state.medium).get_time()

    ### Public Methods ###

    @rpc.publish
    @replay.journaled
    def terminate_hard(self, state):
        self.call_next(state.medium.terminate_hard)

    @rpc.publish
    @replay.journaled
    def terminate(self, state):
        self.call_next(state.medium.terminate)

    @manhole.expose()
    @replay.journaled
    def wait_for_ready(self, state):
        return fiber.wrap_defer(state.medium.wait_for_state,
                                AgencyAgentState.ready)

    @manhole.expose()
    def propose_to(self, recp, partner_role=None, our_role=None):
        return self.establish_partnership(recipient.IRecipient(recp),
                                          partner_role=partner_role,
                                          our_role=our_role)

    @replay.journaled
    def establish_partnership(self, state, recp, allocation_id=None,
                              partner_allocation_id=None,
                              partner_role=None, our_role=None,
                              substitute=None, allow_double=False,
                              max_retries=0):
        f = fiber.succeed()
        found = state.partners.find(recp)
        default_role = getattr(self.partners_class, 'default_role', None)
        our_role = our_role or default_role
        if not allow_double and found:
            msg = ('establish_partnership() called for %r which is already '
                   'our partner with the class %r.' % (recp, type(found), ))
            self.debug(msg)

            if substitute:
                f.add_callback(fiber.drop_param, state.partners.remove,
                               substitute)

            f.chain(fiber.fail(partners.DoublePartnership(msg)))
            return f
#        f.add_callback(fiber.drop_param, self.initiate_protocol,
#                       requester.Propose, recp, allocation_id,
#                       partner_allocation_id,
#                       our_role, partner_role, substitute)
        factory = retrying.RetryingProtocolFactory(requester.Propose,
                                                   max_retries=max_retries)
        f.add_callback(fiber.drop_param, self.initiate_protocol,
                       factory, recp, allocation_id,
                       partner_allocation_id,
                       our_role, partner_role, substitute)
        f.add_callback(fiber.call_param, "notify_finish")
        return f

    @replay.journaled
    def substitute_partner(self, state, partners_recp, recp, alloc_id):
        '''
        Establish the partnership to recp and, when it is successfull
        remove partner with recipient partners_recp.

        Use with caution: The partner which we are removing is not notified
        in any way, so he still keeps link in his description. The correct
        usage of this method requires calling it from two agents which are
        divorcing.
        '''
        partner = state.partners.find(recipient.IRecipient(partners_recp))
        if not partner:
            msg = 'subsitute_partner() did not find the partner %r' %\
                  partners_recp
            self.error(msg)
            return fiber.fail(partners.FindPartnerError(msg))
        return self.establish_partnership(recp, partner.allocation_id,
                                          alloc_id, substitute=partner)

    @manhole.expose()
    @replay.journaled
    def breakup(self, state, recp):
        '''breakup(recp) -> Order the agent to break the partnership with
        the given recipient'''
        recp = recipient.IRecipient(recp)
        partner = self.find_partner(recp)
        if partner:
            return state.partners.breakup(partner)
        else:
            self.warning('We were trying to break up with agent recp %r.,'
                         'but apparently he is not our partner!.', recp)

    @replay.immutable
    def create_partner(self, state, partner_class, recp, allocation_id=None,
                       role=None, substitute=None):
        return state.partners.create(partner_class, recp, allocation_id, role,
                                     substitute)

    @replay.immutable
    def remove_partner(self, state, partner):
        return state.partners.remove(partner)

    @replay.mutable
    def partner_sent_notification(self, state, recp, notification_type,
                                  payload, sender):
        return state.partners.receive_notification(
            recp, notification_type, payload, sender)

    @manhole.expose()
    @replay.immutable
    def query_partners(self, state, name_or_class):
        '''query_partners(name_or_class) ->
              Query the partners by the relation name or partner class.'''
        return state.partners.query(name_or_class)

    @manhole.expose()
    @replay.immutable
    def query_partners_with_role(self, state, name, role):
        return state.partners.query_with_role(name, role)

    @replay.immutable
    def find_partner(self, state, recp_or_agent_id):
        return state.partners.find(recp_or_agent_id)

    @replay.immutable
    def query_partner_handler(self, state, partner_type, role=None):
        return state.partners.query_handler(partner_type, role)

    @manhole.expose()
    @replay.immutable
    def get_own_address(self, state):
        '''get_own_address() -> Return IRecipient representing the agent.'''
        return recipient.IRecipient(state.medium)

    @replay.immutable
    def initiate_protocol(self, state, *args, **kwargs):
        return state.medium.initiate_protocol(*args, **kwargs)

    @replay.immutable
    def retrying_protocol(self, state, *args, **kwargs):
        return state.medium.retrying_protocol(*args, **kwargs)

    @replay.immutable
    def periodic_protocol(self, state, *args, **kwargs):
        return state.medium.periodic_protocol(*args, **kwargs)

    @replay.immutable
    def initiate_task(self, state, *args, **kwargs):
        return state.medium.initiate_task(*args, **kwargs)

    @replay.immutable
    def retrying_task(self, state, *args, **kwargs):
        return state.medium.retrying_task(*args, **kwargs)

    @replay.immutable
    def register_interest(self, state, *args, **kwargs):
        return state.medium.register_interest(*args, **kwargs)

    @replay.immutable
    def get_document(self, state, doc_id):
        return fiber.wrap_defer(state.medium.get_document, doc_id)

    @replay.immutable
    def delete_document(self, state, doc):
        return fiber.wrap_defer(state.medium.delete_document, doc)

    @replay.immutable
    def query_view(self, state, factory, **options):
        return fiber.wrap_defer(state.medium.query_view, factory, **options)

    @replay.immutable
    def save_document(self, state, doc):
        return fiber.wrap_defer(state.medium.save_document, doc)

    @update_descriptor
    def update_descriptor(self, state, desc, method, *args, **kwargs):
        return method(desc, *args, **kwargs)

    @replay.journaled
    def discover_service(self, state, string_or_factory,
                         timeout=3, shard='lobby'):
        initiator = manager.DiscoverService(string_or_factory, timeout)
        recp = recipient.Broadcast(shard=shard,
                                   protocol_id=initiator.protocol_id)

        f = fiber.succeed(initiator)
        f.add_callback(self.initiate_protocol, recp)
        # this contract will always finish in expired state as it is blindly
        # rejecting all it gets
        f.add_callback(manager.ServiceDiscoveryManager.notify_finish)
        f.add_errback(self._expire_handler)
        return f

    @replay.immutable
    def call_next(self, state, method, *args, **kwargs):
        return state.medium.call_next(method, *args, **kwargs)

    @replay.immutable
    def call_later(self, state, time_left, method, *args, **kwargs):
        return state.medium.call_later(time_left, method, *args, **kwargs)

    @replay.immutable
    def cancel_delayed_call(self, state, call_id):
        state.medium.cancel_delayed_call(call_id)

    @replay.immutable
    def observe(self, _method, *args, **kwargs):
        state.medium.observe(_method, *args, **kwargs)

    ### Private Methods ###

    def _expire_handler(self, fail):
        if fail.check(protocols.ProtocolFailed):
            return fail.value.args[0]
        else:
            fail.raiseException()

    @replay.journaled
    def _initiate_partners(self, state):
        desc = self.get_descriptor()
        results = [state.partners.initiate_partner(x) for x in desc.partners]
        fibers = [x for x in results if isinstance(x, fiber.Fiber)]
        f = fiber.FiberList(fibers)
        f.add_callback(fiber.drop_param,
                       state.medium.register_interest,
                       replier.PartnershipProtocol)
        f.add_callback(fiber.drop_param,
                       state.medium.register_interest,
                       replier.ProposalReceiver)
        return f.succeed()
