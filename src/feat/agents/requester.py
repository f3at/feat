from zope.interface import implements, classProvides

from feat.common import log
from feat.interface import requester

'''testing post-receive hook'''


class BaseRequester(log.Logger):
    classProvides(requester.IRequesterFactory)
    implements(requester.IAgentRequester)

    log_category = "requester"
    timeout = 0
    protocol_id = None

    def __init__(self, agent, medium, *args, **kwargs):
        log.Logger.__init__(self, medium)

        self.agent = agent
        self.medium = medium

    def initiate(self):
        '''@see: L{requester.IAgentRequester}'''

    def got_reply(self, reply):
        '''@see: L{requester.IAgentRequester}'''

    def closed(self):
        '''@see: L{requester.IAgentRequester}'''
