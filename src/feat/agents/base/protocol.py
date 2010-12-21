from feat.agents.base import replay


class InitiatorBase(object):
    '''
    This mixin should be mixed into class implementing IInitiator interface.
    '''

    @replay.immutable
    def notify_state(self, state, status):
        return state.medium.wait_for_state(status)

    @replay.immutable
    def notify_finish(self, state):
        return state.medium.notify_finish()
