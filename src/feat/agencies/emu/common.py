# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from twisted.internet import defer


class StateAssertationError(RuntimeError):
    pass


class StateMachineMixin(object):
    
    def __init__(self):
        self.state = None

    def _set_state(self, state):
        if not self.state or not (state == self.state):
            self.log('Changing state from %r to %r', self.state, state)
            self.state = state

    def _ensure_state(self, states):
        if not isinstance(states, list):
            states = [ states ]
        if self.state in states:
            return True
        raise StateAssertationError("Expected state in: %r, was: %r instead" %\
                           (states, self.state))
        
    def _event_handler(self, mapping, event):
        klass = event.__class__
        decision = mapping.get(klass, None)
        if not decision:
            self.warning("Unknown event received %r. Ignoring", event)
            return False
        
        state_before = decision['state_before']
        try:
            self._ensure_state(state_before)
        except StateAssertationError as e:
            self.warning("Received event: %r in state: %r, expected state"
                         "for this method is: %r",
                         klass, self.state, decision['state_before'])
            return False

        state_after = decision['state_after']
        self._set_state(state_after)
        
        d = self._call(decision['method'], event)


