# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import uuid

from feat.common import delay, fiber, serialization, error_handler, log, defer
from feat.interface.protocols import InitiatorFailed
from feat.agents.base import replay


class StateAssertationError(RuntimeError):
    pass


class StateMachineMixin(object):

    _notifier = None

    def __init__(self, state=None):
        self.state = state
        self._notifier = defer.Notifier()

    @serialization.freeze_tag('StateMachineMixin.wait_for_state')
    def wait_for_state(self, state):
        if self.state == state:
            return defer.succeed(None)
        return self._notifier.wait(state)

    def _set_state(self, state):
        if not self.state or not (state == self.state):
            self.log('Changing state from %r to %r', self.state, state)
            self.state = state

        if self._notifier:
            self._notifier.callback(state, None)

    def _cmp_state(self, states):
        if not isinstance(states, list):
            states = [states]
        if self.state in states:
            return True
        return False

    def _ensure_state(self, states):
        if self._cmp_state(states):
            return True
        raise StateAssertationError("Expected state in: %r, was: %r instead" %\
                           (states, self.state))

    def _get_machine_state(self):
        return self.state

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

    # Make it possible to use mixin without the logging submodule

    def log(self, *args):
        if isinstance(self, log.Logger):
            log.Logger.log(self, *args)

    def debug(self, *args):
        if isinstance(self, log.Logger):
            log.Logger.debug(self, *args)

    def info(self, *args):
        if isinstance(self, log.Logger):
            log.Logger.info(self, *args)

    def warning(self, *args):
        if isinstance(self, log.Logger):
            log.Logger.warning(self, *args)

    def error(self, *args):
        if isinstance(self, log.Logger):
            log.Logger.error(self, *args)


class AgencyMiddleMixin(object):
    '''Responsible for formating messages, calling methods etc'''

    protocol_id = None
    session_id = None
    remote_id = None

    error_state = None

    def __init__(self, remote_id=None, protocol_id=None):
        self.session_id = str(uuid.uuid1())
        self._set_remote_id(remote_id)
        self._set_protocol_id(protocol_id)

    def _set_remote_id(self, remote_id):
        if self.remote_id is not None:
            self.debug('Changing id of remote peer. This usually means the '
                       'message has been handed over.')
        self.remote_id = remote_id

    def _set_protocol_id(self, protocol_id):
        self.protocol_id = protocol_id

    def _send_message(self, msg, expiration_time=None, recipients=None,
                      remote_id=None):
        msg.sender_id = self.session_id
        msg.receiver_id = remote_id or self.remote_id
        msg.protocol_id = self.protocol_id
        if msg.expiration_time is None:
            if expiration_time is None:
                expiration_time = self.agent.get_time() + 10
            msg.expiration_time = expiration_time

        if not recipients:
            recipients = self.recipients

        return self.agent.send_msg(recipients, msg)

    def _handover_message(self, msg, remote_id=None):
        msg.receiver_id = remote_id or self.remote_id
        return self.agent.send_msg(self.recipients, msg, handover=True)

    def _call(self, method, *args, **kwargs):
        '''Call the method, wrap it in Deferred and bind error handler'''

        #FIXME: we shouldn't need maybe_fiber, mabeDeferred should be enough
        d = fiber.maybe_fiber(method, *args, **kwargs)
        d.addErrback(self._error_handler)
        return d

    def _error_handler(self, f):
        error_handler(self, f)
        self._set_state(self.error_state)
        self._terminate()


class ExpirationCallsMixin(object):

    def __init__(self):
        self._expiration_call = None

    def _get_time(self):
        raise NotImplemented('Should be define in the class using the mixin')

    def _setup_expiration_call(self, expire_time, method, state=None,
                                  *args, **kwargs):
        self.log('Seting expiration call of method: %r.%r',
                 self.__class__.__name__, method.__name__)

        time_left = expire_time - self._get_time()
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
        self._expiration_call = delay.callLater(
            time_left, to_call, result)
        return result

    def _expire_at(self, expire_time, method, state, *args, **kwargs):
        d = self._setup_expiration_call(expire_time, method,
                                           state, *args, **kwargs)
        d.addCallback(lambda _: self._terminate())
        return d

    @replay.side_effect
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

    def expire_now(self):
        if self._expiration_call and not (self._expiration_call.called or\
                                          self._expiration_call.cancelled):
            self._expiration_call.reset(0)
            d = self.notify_finish()
            return d
        else:
            self.error('Expiration call %r is None or was already called or'
                       'cancelled', self._expiration_call)


class InitiatorMediumBase(object):

    error_factory = InitiatorFailed

    def __init__(self):
        self._finished_cbs = list()
        self.finish_deferred = defer.Deferred()
        self.finish_deferred.addCallbacks(self._finish_callback,
                                           self._finish_errback)

    def notify_finish(self):
        d = defer.Deferred()
        self._finished_cbs.append(d)
        return d

    def _finish_callback(self, x):
        map(lambda d: d.callback(x), self._finished_cbs)
        return x

    def _finish_errback(self, x):
        for d in self._finished_cbs:
            d.errback(x)

    def _terminate(self):
        if not self.finish_deferred.called:
            self.log("Firing errback of finish_deferred")
            ex = self.error_factory(self.state)
            self.finish_deferred.errback(ex)


class InterestedMediumBase(InitiatorMediumBase):

    def _terminate(self):
        if not self.finish_deferred.called:
            self.finish_deferred.callback(None)
