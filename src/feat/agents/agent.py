# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from zope.interface import implements, classProvides

from feat.interface import agent


class BaseAgent(object):
    '''
    Starting an agent:
        > descriptor = Descriptor(uuid="007", shard="lobby")
        > agency.start_agent(MyAgent, descriptor, some_extra_params)
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


#class ShardAgent(BaseAgent):

