# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import traceback

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
            states = [states]
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
        except StateAssertationError:
            self.warning("Received event: %r in state: %r, expected state "
                         "for this method is: %r",
                         klass, self.state, decision['state_before'])
            return False

        state_after = decision['state_after']
        self._set_state(state_after)

        self._call(decision['method'], event)


class AgencyMiddleMixin(object):
    '''Responsible for formating messages, calling methods etc'''

    protocol_id = None
    session_id = None

    error_state = None

    def __init__(self, protocol_id):
        self.protocol_id = protocol_id

    def _send_message(self, msg, expiration_time=None, recipients=None):
        msg.session_id = self.session_id
        msg.protocol_id = self.protocol_id
        if msg.expiration_time is None:
            if expiration_time is None:
                expiration_time = self.agent.get_time() + 10
            msg.expiration_time = expiration_time

        if not recipients:
            recipients = self.recipients

        return self.agent.send_msg(recipients, msg)

    def _call(self, method, *args, **kwargs):
        '''Call the method, wrap it in Deferred and bind error handler'''

        d = defer.maybeDeferred(method, *args, **kwargs)
        d.addErrback(self._error_handler)
        return d

    def _error_handler(self, e):
        msg = e.getErrorMessage()
        self.error('Terminating: %s', msg)

        frames = traceback.extract_tb(e.getTracebackObject())
        if len(frames) > 0:
            self.error('Last traceback frame: %r', frames[-1])

        self._set_state(self.error_state)
        self._terminate()


class ExpirationCallsMixin(object):

    def __init__(self):
        self._expiration_call = None

    def _setup_expiration_call(self, expire_time, method, state=None,
                                  *args, **kwargs):
        time_left = expire_time - self.agent.get_time()

        if time_left < 0:
            raise RuntimeError('Tried to call method in the past!')

        def to_call(callback):
            if state:
                self._set_state(state)
            self.log('Calling method: %r with args: %r', method, args)
            d = defer.maybeDeferred(method, *args, **kwargs)
            d.addErrback(self._error_handler)
            d.addCallback(callback.callback)

        result = defer.Deferred()
        self._expiration_call = self.agent.callLater(
            time_left, to_call, result)
        return result

    def _expire_at(self, expire_time, method, state, *args, **kwargs):
        d = self._setup_expiration_call(expire_time, method,
                                           state, *args, **kwargs)
        d.addCallback(lambda _: self._terminate())
        return d

    def _cancel_expiration_call(self):
        if self._expiration_call and not (self._expiration_call.called or\
                                          self._expiration_call.cancelled):
            self.log('Canceling expiration call')
            self._expiration_call.cancel()
            self._expiration_call = None

    def _run_and_terminate(self, method, *args, **kwargs):
        d = self._call(method, *args, **kwargs)
        d.addCallback(lambda _: self._terminate())

    def _terminate(self):
        self._cancel_expiration_call()
