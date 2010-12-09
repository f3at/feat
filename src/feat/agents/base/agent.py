# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from zope.interface import implements, classProvides

from feat.common import log
from feat.interface import agent


registry = dict()


def register(klass):
    global registry
    registry[klass.__name__] = klass
    return klass


def registry_lookup(name):
    global registry
    if name in registry:
        return registry[name]
    return None


class BaseAgent(log.Logger):

    log_category = "agent"

    classProvides(agent.IAgentFactory)
    implements(agent.IAgent)

    def __init__(self, medium):
        log.Logger.__init__(self, medium)
        self.medium = agent.IAgencyAgent(medium)

    ## IAgent Methods ##

    def initiate(self):
        pass
