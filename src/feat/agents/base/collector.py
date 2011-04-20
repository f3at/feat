from zope.interface import implements

from feat.common import log, defer, reflect, serialization, fiber
from feat.agents.base import message, replay

from feat.interface.protocols import *
from feat.interface.collector import *


class Meta(type(replay.Replayable)):

    implements(ICollectorFactory)

    def __init__(cls, name, bases, dct):
        cls.type_name = reflect.canonical_name(cls)
        serialization.register(cls)
        super(Meta, cls).__init__(name, bases, dct)


class BaseCollector(log.Logger, replay.Replayable):

    __metaclass__ = Meta

    implements(IAgentCollector)

    initiator = message.Notification
    interest_type = InterestType.private

    log_category = "collector"
    protocol_type = "Notification"
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

    def notified(self, notification):
        '''@see: L{IAgentCollector}'''
