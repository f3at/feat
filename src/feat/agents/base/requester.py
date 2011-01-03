from zope.interface import implements, classProvides

from feat.common import log
from feat.interface import requester
from feat.agencies import agency
from feat.agents.base import replay, protocol


class Meta(type(replay.Replayable)):
    implements(requester.IRequesterFactory)


class BaseRequester(log.Logger, protocol.InitiatorBase, replay.Replayable):

    __metaclass__ = Meta
    implements(requester.IAgentRequester)

    log_category = "requester"
    timeout = 0
    protocol_id = None

    def __init__(self, agent, medium, *args, **kwargs):
        log.Logger.__init__(self, medium)
        replay.Replayable.__init__(self, agent, medium, *args, **kwargs)

    def init_state(self, state, agent, medium, *args, **kwargs):
        state.agent = agent
        state.medium = medium

    def initiate(self):
        '''@see: L{requester.IAgentRequester}'''

    def got_reply(self, reply):
        '''@see: L{requester.IAgentRequester}'''

    def closed(self):
        '''@see: L{requester.IAgentRequester}'''
