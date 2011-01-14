# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from zope.interface import implements

from feat.common import log, decorator, serialization, fiber
from feat.interface import agent
from feat.agents.base import resource, recipient, replay

registry = dict()


@decorator.parametrized_class
def register(klass, name):
    global registry
    registry[name] = klass
    klass.descriptor_type = name
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
        if resp:
            f.add_callback(lambda _: resp)
        return f.succeed(desc)

    return decorated


class MetaAgent(type(replay.Replayable)):
    implements(agent.IAgentFactory)


class BaseAgent(log.Logger, log.LogProxy, replay.Replayable):

    __metaclass__ = MetaAgent

    implements(agent.IAgent)

    def __init__(self, medium):
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

    ## IAgent Methods ##

    def initiate(self):
        pass

    @replay.immutable
    def get_own_address(self, state):
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

    @replay.mutable
    def release_resource(self, state, allocation):
        return state.resources.release(allocation)

    @replay.immutable
    def get_time(self, state):
        return state.medium.get_time()

    @replay.immutable
    def get_document(self, state, doc_id):
        return state.medium.get_document(doc_id)
