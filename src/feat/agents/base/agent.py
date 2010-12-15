# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from zope.interface import implements

from feat.common import log, decorator
from feat.interface import agent


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


class Meta(type):
    implements(agent.IAgentFactory)


class BaseAgent(log.Logger, log.LogProxy):

    __metaclass__ = Meta

    implements(agent.IAgent)

    def __init__(self, medium):
        log.Logger.__init__(self, medium)
        self.medium = agent.IAgencyAgent(medium)

    ## IAgent Methods ##

    def initiate(self):
        pass
