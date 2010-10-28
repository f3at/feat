# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from zope.interface import implements, classProvides
from twisted.python import components

from feat.interface import agent, recipient, protocols
from feat.interface.requester import IRequesterFactory, IAgentRequester
from feat.agents import requester 

import message

import uuid

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


class RequestResponder(object):
    implements(protocols.IListener)

    def __init__(self, requester):
        self.requester = requester

    def on_message(self, message):
        requester.got_reply(message)

    def get_session_id(self):
        self.requester.medium.session_id


components.registerAdapter(RequestResponder, IAgentRequester, \
                                           protocols.IListener)
