from twisted.internet import defer

from feat.agents.base import replay


class StateAssertationError(RuntimeError):
    pass


class ReplayableStateMachine(replay.Replayable):
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

    def _event_handler(self, mapping, event):
        klass = event.__class__
        decision = mapping.get(klass, None)
        if not decision:
            self.warning("Unknown event received %r. Ignoring", event)
            return False

        if isinstance(decision, list):
            match = filter(
                lambda x: self._cmp_state(x['state_before']), decision)
            if len(match) != 1:
                self.warning("Expected to find excatly one handler for %r in "
                             "state %r, found %r handlers", event,
                             self.get_machine_state(),
                             len(match))
                return False
            decision = match[0]

        state_before = decision['state_before']
        try:
            self._ensure_state(state_before)
        except StateAssertationError:
            self.warning("Received event: %r in state: %r, expected state "
                         "for this method is: %r",
                         klass, self._get_machine_state(),
                         decision['state_before'])
            return False

        state_after = decision['state_after']
        self._set_state(state_after)

        self._call(decision['method'], event)
