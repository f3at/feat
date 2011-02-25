# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from zope.interface import implements

from feat.common import log, decorator, serialization, fiber, manhole
from feat.interface import agent
from feat.agents.base import (resource, recipient, replay, requester,
                              replier, partners, dependency, )


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
def update_descriptor(method):

    @replay.immutable
    def decorated(self, state, *args, **kwargs):
        desc = state.medium.get_descriptor()
        resp = method(self, state, desc, *args, **kwargs)
        f = fiber.Fiber()
        f.add_callback(state.medium.update_descriptor)
        f.add_callback(lambda _: resp)
        return f.succeed(desc)

    return decorated


class MetaAgent(type(replay.Replayable), type(manhole.Manhole)):
    implements(agent.IAgentFactory)


class BaseAgent(log.Logger, log.LogProxy, replay.Replayable, manhole.Manhole,
                dependency.AgentDependencyMixin):

    __metaclass__ = MetaAgent

    implements(agent.IAgent)

    partners_class = partners.Partners

    standalone = False

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
        state.resources = resource.Resources(self)
        state.partners = self.partners_class(self)

    ## IAgent Methods ##

    @replay.immutable
    def initiate(self, state):
        self._load_allocations()
        state.medium.register_interest(replier.GoodBye)
        state.medium.register_interest(replier.ProposalReceiver)

    @replay.journaled
    def shutdown(self, state):
        desc = self.get_descriptor()
        self.info('Agent shutdown, partners: %r', desc.partners)
        results = [x.on_shutdown(self) for x in desc.partners]
        fibers = [x for x in results if isinstance(x, fiber.Fiber)]
        f = fiber.FiberList(fibers)
        return f.succeed()

    def get_cmd_line(self):
        raise NotImplemented('To be used for standalone agents!')

    ## end of IAgent ##

    @replay.journaled
    def initiate_partners(self, state):
        desc = self.get_descriptor()
        results = [x.initiate(self) for x in desc.partners]
        fibers = [x for x in results if isinstance(x, fiber.Fiber)]
        f = fiber.FiberList(fibers)
        return f.succeed()

    @manhole.expose()
    def propose_to(self, recp):
        return self.establish_partnership(recipient.IRecipient(recp))

    @replay.journaled
    def establish_partnership(self, state, recp, allocation_id=None,
                              partner_role=None, our_role=None):
        found = state.partners.find(recp)
        if found:
            self.debug('establish_partnership() called for %r which is already'
                       'our partner with the class %r, ignoring',
                       recp, type(found))
            return found
        f = fiber.Fiber()
        f.add_callback(self.initiate_protocol, recp, allocation_id,
                       partner_role, our_role)
        f.add_callback(requester.Propose.notify_finish)
        return f.succeed(requester.Propose)

    @replay.immutable
    def create_partner(self, state, partner_class, recp, allocation_id=None,
                       role=None):
        return state.partners.create(partner_class, recp, allocation_id, role)

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
    def list_resource(self, state):
        allocated = state.resources.allocated()
        totals = state.resources.get_totals()
        return totals, allocated

    @replay.mutable
    def confirm_allocation(self, state, allocation_id):
        return state.resources.confirm(allocation_id)

    @replay.mutable
    def release_resource(self, state, allocation_id):
        return state.resources.release(allocation_id)

    @replay.immutable
    def get_time(self, state):
        return state.medium.get_time()

    @replay.immutable
    def get_document(self, state, doc_id):
        return state.medium.get_document(doc_id)

    @replay.immutable
    def save_document(self, state, doc):
        return state.medium.save_document(doc)

    @update_descriptor
    def update_descriptor(self, state, desc, method, *args, **kwargs):
        return method(desc, *args, **kwargs)

    # private

    @replay.mutable
    def _load_allocations(self, state):
        desc = self.get_descriptor()
        state.resources.load(desc.allocations)
