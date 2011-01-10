from zope.interface import implements, classProvides

from feat.common import log, reflect, serialization
from feat.interface import requester
from feat.agencies import agency
from feat.agents.base import replay, protocol


class Meta(type(replay.Replayable)):
    implements(requester.IRequesterFactory)

    def __init__(cls, name, bases, dct):
        cls.type_name = reflect.canonical_name(cls)
        serialization.register(cls)
        super(Meta, cls).__init__(name, bases, dct)


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

    @replay.immutable
    def restored(self, state):
        replay.Replayable.restored(self)
        log.Logger.__init__(self, state.medium)

    def initiate(self):
        '''@see: L{requester.IAgentRequester}'''

    def got_reply(self, reply):
        '''@see: L{requester.IAgentRequester}'''

    def closed(self):
        '''@see: L{requester.IAgentRequester}'''
