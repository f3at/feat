from feat.agents.base import replay
from feat.common import fiber


class InitiatorBase(object):
    '''
    This mixin should be mixed into class implementing IInitiator interface.
    '''

    @replay.journaled
    def notify_state(self, state, *states):
        return fiber.wrap_defer(state.medium.wait_for_state, *states)

    @replay.journaled
    def notify_finish(self, state):
        return fiber.wrap_defer(state.medium.notify_finish)
