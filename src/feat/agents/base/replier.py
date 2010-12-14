from zope.interface import implements, classProvides

from feat.interface import replier, protocols
from feat.common import log
from feat.agents.base import message


class Meta(type):
    implements(replier.IReplierFactory)


class BaseReplier(log.Logger):

    __metaclass__ = Meta

    implements(replier.IAgentReplier)

    initiator = message.RequestMessage
    interest_type = protocols.InterestType.private

    log_category = "replier"
    protocol_type = "Request"
    protocol_id = None

    def __init__(self, agent, medium):
        log.Logger.__init__(self, medium)

        self.agent = agent
        self.medium = medium

    def requested(self, request):
        '''@see: L{replier.IAgentReplier}'''
