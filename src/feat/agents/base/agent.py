# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import types

from zope.interface import implements

from feat.common import log, decorator, serialization, fiber, manhole
from feat.interface import generic, agent, protocols
from feat.agents.base import (resource, recipient, replay, requester,
                              replier, partners, dependency, manager,
                              protocol, )


registry = dict()


@decorator.parametrized_class
def register(klass, name):
    global registry
    registry[name] = klass
    klass.descriptor_type = name
    klass.type_name = name + ":data"
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


class MetaAgent(type(replay.Replayable), type(manhole.Manhole)):
    implements(agent.IAgentFactory)


class BaseAgent(log.Logger, log.LogProxy, replay.Replayable, manhole.Manhole,
                dependency.AgentDependencyMixin):

    __metaclass__ = MetaAgent

    implements(agent.IAgent, generic.ITimeProvider)

    partners_class = partners.Partners

    log_category = "agent"

    standalone = False

    categories = {'access': agent.Access.none,
                  'address': agent.Address.none,
                  'storage': agent.Storage.none}

    def __init__(self, medium):
        manhole.Manhole.__init__(self)
        log.Logger.__init__(self, medium)
        log.LogProxy.__init__(self, medium)
        replay.Replayable.__init__(self, medium)
        self.log_name = self.__class__.__name__

    @replay.immutable
    def restored(self, state):
        log.Logger.__init__(self, state.medium)
        log.LogProxy.__init__(self, state.medium)
        replay.Replayable.restored(self)

    def init_state(self, state, medium):
        state.medium = agent.IAgencyAgent(medium)
        state.resources = resource.Resources(self)
        state.partners = self.partners_class(self)

    ### IAgent Methods ###

    @replay.immutable
    def initiate(self, state):
        self._load_allocations()
        state.medium.register_interest(replier.GoodBye)
        state.medium.register_interest(replier.ProposalReceiver)

    @replay.immutable
    def startup(self, state):
        pass

    @replay.journaled
    def shutdown(self, state):
        desc = self.get_descriptor()
        self.info('Agent shutdown, partners: %r', desc.partners)
        results = [x.on_shutdown(self) for x in desc.partners]
        fibers = [x for x in results if isinstance(x, fiber.Fiber)]
        f = fiber.FiberList(fibers)
        return f.succeed()

    def on_killed(self):
        self.info('Agents on_killed called.')

    def get_cmd_line(self, *args, **kwargs):
        raise NotImplemented('To be used for standalone agents!')

    ### ITimeProvider Methods ###

    @replay.immutable
    def get_time(self, state):
        return generic.ITimeProvider(state.medium).get_time()

    ### Public Methods ###

    @replay.journaled
    def initiate_partners(self, state):
        desc = self.get_descriptor()
        results = [x.initiate(self) for x in desc.partners]
        fibers = [x for x in results if isinstance(x, fiber.Fiber)]
        f = fiber.FiberList(fibers)
        return f.succeed()

    @manhole.expose()
    def propose_to(self, recp, partner_role=None):
        return self.establish_partnership(recipient.IRecipient(recp),
                                          partner_role=partner_role)

    @replay.journaled
    def establish_partnership(self, state, recp, allocation_id=None,
                              partner_allocation_id=None,
                              partner_role=None, our_role=None,
                              substitute=None):
        f = fiber.succeed()
        found = state.partners.find(recp)
        if found:
            msg = ('establish_partnership() called for %r which is already '
                   'our partner with the class %r.' % (recp, type(found), ))
            self.debug(msg)

            if substitute:
                f.add_callback(fiber.drop_result, state.partners.remove,
                               substitute)

            f.chain(fiber.fail(partners.DoublePartnership(msg)))
            return f
        f.add_callback(fiber.drop_result, self.initiate_protocol,
                       requester.Propose, recp, allocation_id,
                       partner_allocation_id,
                       partner_role, our_role, substitute)
        f.add_callback(requester.Propose.notify_finish)
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

    @replay.immutable
    def create_partner(self, state, partner_class, recp, allocation_id=None,
                       role=None, substitute=None):
        return state.partners.create(partner_class, recp, allocation_id, role,
                                     substitute)

    @replay.mutable
    def partner_said_goodbye(self, state, recp):
        return state.partners.on_goodbye(recp)

    @manhole.expose()
    @replay.immutable
    def query_partners(self, state, name):
        '''query_partners(name) -> Query the partners by the relation name.'''
        return state.partners.query(name)

    @manhole.expose()
    @replay.immutable
    def get_own_address(self, state):
        '''get_own_address() -> Return IRecipient representing the agent.'''
        return recipient.IRecipient(state.medium)

    @replay.immutable
    def get_descriptor(self, state):
        return state.medium.get_descriptor()

    @replay.immutable
    def initiate_protocol(self, state, *args, **kwargs):
        return state.medium.initiate_protocol(*args, **kwargs)

    @replay.mutable
    def preallocate_resource(self, state, **params):
        return state.resources.preallocate(**params)

    @replay.mutable
    def allocate_resource(self, state, **params):
        return state.resources.allocate(**params)

    @replay.immutable
    def check_allocation_exists(self, state, allocation_id):
        return state.resources.exists(allocation_id)

    @replay.immutable
    def list_resource(self, state):
        allocated = state.resources.allocated()
        totals = state.resources.get_totals()
        return totals, allocated

    @replay.mutable
    def confirm_allocation(self, state, allocation_id):
        return state.resources.confirm(allocation_id)

    @replay.immutable
    def allocation_used(self, state, allocation_id):
        '''
        Checks if allocation is used by any of the partners.
        If allocation does not exist returns False.
        @param allocation_id: ID of the allocation
        @returns: True/False
        '''
        return len(filter(lambda x: x.allocation_id == allocation_id,
                          state.partners.all)) > 0

    @replay.mutable
    def release_resource(self, state, allocation_id):
        return state.resources.release(allocation_id)

    @replay.immutable
    def get_document(self, state, doc_id):
        return state.medium.get_document(doc_id)

    @replay.immutable
    def save_document(self, state, doc):
        return state.medium.save_document(doc)

    @update_descriptor
    def update_descriptor(self, state, desc, method, *args, **kwargs):
        return method(desc, *args, **kwargs)

    @replay.journaled
    def discover_service(self, state, factory, timeout=3, shard='lobby'):

        def expire_handler(fail):
            if fail.check(protocols.InitiatorFailed):
                return fail.value.args[0]
            else:
                fail.raiseException()

        initiator = manager.DiscoverService(factory, timeout)
        recp = recipient.Broadcast(shard=shard,
                                   protocol_id=initiator.protocol_id)
        f = fiber.succeed(initiator)
        f.add_callback(self.initiate_protocol, recp)
        # this contract will always finish in expired state as it is blindly
        # rejecting all it gets
        f.add_callback(manager.ServiceDiscoveryManager.notify_finish)
        f.add_errback(expire_handler)
        return f

    ### Private Methods ###

    @replay.mutable
    def _load_allocations(self, state):
        desc = self.get_descriptor()
        state.resources.load(desc.allocations)
