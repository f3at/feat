from zope.interface import implements, classProvides

from feat.interface import replier, protocols
from feat.common import log, reflect, serialization
from feat.agents.base import message, replay


class Meta(type(replay.Replayable)):
    implements(replier.IReplierFactory)

    def __init__(cls, name, bases, dct):
        cls.type_name = reflect.canonical_name(cls)
        serialization.register(cls)
        super(Meta, cls).__init__(name, bases, dct)


class BaseReplier(log.Logger, replay.Replayable):

    __metaclass__ = Meta

    implements(replier.IAgentReplier)

    initiator = message.RequestMessage
    interest_type = protocols.InterestType.private

    log_category = "replier"
    protocol_type = "Request"
    protocol_id = None

    def __init__(self, agent, medium):
        log.Logger.__init__(self, medium)
        replay.Replayable.__init__(self, agent, medium)

    def init_state(self, state, agent, medium):
        state.agent = agent
        state.medium = medium

    @replay.immutable
    def restored(self, state):
        replay.Replayable.restored(self)
        log.Logger.__init__(self, state.medium)

    def requested(self, request):
        '''@see: L{replier.IAgentReplier}'''
