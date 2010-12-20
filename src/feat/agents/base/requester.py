from zope.interface import implements, classProvides

from feat.common import log
from feat.interface import requester
from feat.agencies import agency


class Meta(type):
    implements(requester.IRequesterFactory)


class BaseRequester(log.Logger, agency.InitiatorMixin):

    __metaclass__ = Meta
    implements(requester.IAgentRequester)

    log_category = "requester"
    timeout = 0
    protocol_id = None

    def __init__(self, agent, medium, *args, **kwargs):
        log.Logger.__init__(self, medium)

        self.agent = agent
        self.medium = medium
        agency.InitiatorMixin.__init__(self)

    def initiate(self):
        '''@see: L{requester.IAgentRequester}'''

    def got_reply(self, reply):
        '''@see: L{requester.IAgentRequester}'''

    def closed(self):
        '''@see: L{requester.IAgentRequester}'''
