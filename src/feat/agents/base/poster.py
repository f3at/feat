from zope.interface import implements

from feat.common import log, defer, reflect, serialization, fiber
from feat.agents.base import message, replay

from feat.interface.protocols import *
from feat.interface.poster import *


class Meta(type(replay.Replayable)):

    implements(IPosterFactory)

    def __init__(cls, name, bases, dct):
        cls.type_name = reflect.canonical_name(cls)
        serialization.register(cls)
        super(Meta, cls).__init__(name, bases, dct)


class BasePoster(log.Logger, replay.Replayable):

    __metaclass__ = Meta

    implements(IAgentPoster)

    log_category = "poster"
    protocol_type = "Notification"
    protocol_id = None
    notification_timeout = 10

    def __init__(self, agent, medium):
        log.Logger.__init__(self, medium)
        replay.Replayable.__init__(self, agent, medium)

    def init_state(self, state, agent, medium):
        state.agent = agent
        state.medium = medium

    ### Method to be Overridden ###

    def pack_payload(self, *args, **kwargs):
        return dict(args=args, kwars=kwargs)

    ### IAgentPoster Methods ###

    def initiate(self):
        '''Nothing, arguments not supported.'''

    def notify(self, *args, **kwargs):
        d = defer.maybeDeferred(self.pack_payload, *args, **kwargs)
        d.addCallback(self._build_message)
        return d

    ### Private Methods ###

    @replay.immutable
    def _build_message(self, state, payload):
        msg = message.Notification()
        msg.payload = payload
        return state.medium.post(msg)
