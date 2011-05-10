from zope.interface import implements

from feat.agents.base import replay
from feat.common import log, fiber

from feat.interface.protocols import *


class BaseProtocol(log.Logger, replay.Replayable):

    implements(IAgentProtocol)

    log_category = "protocol"

    protocol_type = None
    protocol_id = None

    def __init__(self, agent, medium):
        log.Logger.__init__(self, medium)
        replay.Replayable.__init__(self, agent, medium)

    @replay.immutable
    def restored(self, state):
        replay.Replayable.restored(self)
        log.Logger.__init__(self, state.medium)

    def init_state(self, state, agent, medium):
        state.agent = agent
        state.medium = medium

    ### IAgentProtocol ###

    def initiate(self):
        '''@see: L{contractor.IAgentContractor}'''

    @replay.immutable
    def cancel(self, state):
        return state.medium._terminate(ProtocolCancelled())

    @replay.immutable
    def is_idle(self, state):
        return state.medium.is_idle()


class BaseInitiator(BaseProtocol):

    implements(IInitiator)

    @replay.journaled
    def notify_state(self, state, *states):
        return fiber.wrap_defer(state.medium.wait_for_state, *states)

    @replay.journaled
    def notify_finish(self, state):
        return fiber.wrap_defer(state.medium.notify_finish)

    @replay.immutable
    def get_expiration_time(self, state):
        return state.medium.get_expiration_time()


class BaseInterested(BaseProtocol):

    implements(IInterested)

    initiator = None
    interest_type = None

    @replay.immutable
    def get_expiration_time(self, state):
        return state.medium.get_expiration_time()
