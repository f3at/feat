# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from zope.interface import implements, classProvides
from twisted.python import components

from feat.interface import agent, recipient, protocols
from feat.interface.requester import IRequesterFactory, IAgentRequester
from feat.agents import requester
from feat.common import log

import message

import uuid

class BaseAgent(log.Logger):
    '''
    Didn't have time to fix unit tests so I changed the name.
    We should discuss about this.
    '''

    log_category = "agent"

    classProvides(agent.IAgentFactory)
    implements(agent.IAgent)

    def __init__(self, medium):
        log.Logger.__init__(self, medium)
        self.medium = agent.IAgencyAgent(medium)

    ## IAgent Methods ##

    def initiate(self):
        pass


