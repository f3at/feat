from twisted.internet import defer

from feat.agents.base import replay
from feat.agencies import common


class StateAssertationError(RuntimeError):
    pass


class ReplayableStateMachine(replay.Replayable, common.StateMachineMixin):
    # StateMachine implementation consistent with replayability

    def __init__(self, agent, machine_state, *args, **kwargs):
        replay.Replayable.__init__(self, agent, machine_state, *args, **kwargs)
        self._changes_notifications = dict()

    def init_state(self, state, agent, machine_state=None):
        state.agent = agent
        state.machine_state = machine_state

    @replay.immutable
    def _get_machine_state(self, state):
        return state.machine_state

    @replay.mutable
    def _do_set_state(self, state, machine_state):
        if not state.machine_state or \
                not (machine_state == state.machine_state):
            self.log('Changing state from %r to %r', state.machine_state,
                     machine_state)
            state.machine_state = machine_state

    @replay.side_effect
    def _set_state(self, machine_state):
        self._do_set_state(machine_state)
        if machine_state in self._changes_notifications:
            for cb in self._changes_notifications[machine_state]:
                cb.callback(None)
            del(self._changes_notifications[machine_state])

    @replay.immutable
    def wait_for_state(self, state, machine_state):
        if state.machine_state == machine_state:
            return defer.succeed(None)
        d = defer.Deferred()
        if machine_state not in self._changes_notifications:
            self._changes_notifications[machine_state] = [d]
        else:
            self._changes_notifications[machine_state].append(d)
        return d

    @replay.immutable
    def _ensure_state(self, state, states):
        if self._cmp_state(states):
            return True
        raise RuntimeError("Expected state in: %r, was: %r instead" %\
                           (states, state.state))

    def _cmp_state(self, states):
        if not isinstance(states, list):
            states = [states]
        if self._get_machine_state() in states:
            return True
        return False
