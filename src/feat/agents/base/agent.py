# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from zope.interface import implements

from feat.common import log, decorator
from feat.interface import agent
from feat.agents.base import resource, recipient


registry = dict()


@decorator.parametrized_class
def register(klass, name):
    global registry
    registry[name] = klass
    return klass


def registry_lookup(name):
    global registry
    if name in registry:
        return registry[name]
    return None


def update_descriptor(method):

    def decorated(self, *args, **kwargs):
        desc = self.medium.get_descriptor()
        resp = method(self, desc, *args, **kwargs)
        d = self.medium.update_descriptor(desc)
        if resp:
            d.addCallback(lambda _: resp)
        return d

    return decorated


class Meta(type):
    implements(agent.IAgentFactory)


class BaseAgent(log.Logger, log.LogProxy):

    __metaclass__ = Meta

    implements(agent.IAgent)

    def __init__(self, medium):
        log.Logger.__init__(self, medium)
        log.LogProxy.__init__(self, medium)

        self.medium = agent.IAgencyAgent(medium)
        self.resources = resource.Resources(self)

    ## IAgent Methods ##

    def initiate(self):
        pass

    def get_own_address(self):
        return recipient.IRecipient(self.medium)
