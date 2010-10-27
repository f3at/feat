# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from zope.interface import implements, classProvides

from feat.interface import agent


class BaseAgent(object):
    '''
    Didn't have time to fix unit tests so I changed the name.
    We should discuss about this.
    '''

    classProvides(agent.IAgentFactory)
    implements(agent.IAgent)

    def __init__(self, medium):
        self.medium = medium

    ## IAgent Methods ##

    def initiate(self):
        pass

    def snapshot(self):
        pass



