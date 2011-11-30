# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import uuid

from zope.interface import implements, classProvides
from feat.interface.fiber import ICancellable, FiberCancelled
from feat.interface.log import LogLevel
from twisted.python import failure

from feat.common import log, defer, fiber, observer, time, enum
from feat.common import serialization, error_handler, mro, error, first
from feat.agents.base import replay

from feat.interface.protocols import ProtocolFailed, ProtocolExpired
from feat.interface.serialization import IRestorator


class Statistics(object):

    def __init__(self):
        self._statistics = dict()

    def increase_stat(self, key, value=1):
        if key not in self._statistics:
            self._statistics[key] = 0
        self._statistics[key] += value

    def get_stats(self):
        return self._statistics.items()


class StateAssertationError(RuntimeError):
    pass


class StateMachineMixin(object):
    '''
    Mixin used by numerous objects. Defines the state and provides utilities
    for making decisions based on state.
    '''

    _notifier = None

    def __init__(self, state=None):
        self.state = state
        self._notifier = defer.Notifier()

    @serialization.freeze_tag('StateMachineMixin.wait_for_state')
    def wait_for_state(self, *states):
        if self.state in states:
            return defer.succeed(self)
        d = defer.DeferredList(
            map(lambda state: self._notifier.wait(state), states),
            fireOnOneCallback=True)
        d.addCallback(lambda _: self)
        return d

    def _set_state(self, state):
        if not self.state or not (state == self.state):
            self.log('Changing state from %r to %r', self.state, state)
            self.state = state

        if self._notifier:
            self._notifier.callback(state, self)

    def _cmp_state(self, states):
        if not isinstance(states, (list, tuple, )):
            states = [states]
        return self.state in states

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
                             self._get_machine_state(),
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

    def log(self, format, *args):
        if isinstance(self, log.Logger):
            #TODO: logging depth seems broken, change this when fixed
            log.Logger.logex(self, LogLevel.log, format, args, depth=-3)

    def debug(self, format, *args):
        if isinstance(self, log.Logger):
            #TODO: logging depth seems broken, change this when fixed
            log.Logger.logex(self, LogLevel.debug, format, args, depth=-3)

    def info(self, format, *args):
        if isinstance(self, log.Logger):
            #TODO: logging depth seems broken, change this when fixed
            log.Logger.logex(self, LogLevel.info, format, args, depth=-3)

    def warning(self, format, *args):
        if isinstance(self, log.Logger):
            #TODO: logging depth seems broken, change this when fixed
            log.Logger.logex(self, LogLevel.warning, format, args, depth=-3)

    def error(self, format, *args):
        if isinstance(self, log.Logger):
            #TODO: logging depth seems broken, change this when fixed
            log.Logger.logex(self, LogLevel.error, format, args, depth=-3)

    # Fiber Canceller

    @replay.named_side_effect('StateMachineMixin.get_canceller')
    def get_canceller(self):
        return StateCanceller(self)


@serialization.register
class StateCanceller(object):

    type_name = 'canceller'

    classProvides(serialization.IRestorator)
    implements(serialization.ISerializable, ICancellable)

    def __init__(self, state_machine):
        self.state = state_machine._get_machine_state()
        self.sm = state_machine

    ### ICancellable methods ###

    def is_active(self):
        if self.sm and self.state == self.sm._get_machine_state():
            return True
        else:
            self.sm = None
            return False

    ### IRestorator Methods ###

    @classmethod
    def prepare(cls):
        return None

    @classmethod
    def restore(cls, snapshot):
        return cls.__new__(cls)

    ### ISerializable Methods ###

    def snapshot(self):
        return (self.state, self.sm)

    ### Private Methods ###

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return self.state == other.state and \
               self.sm == other.sm

    def __ne__(self, other):
        return not self.__eq__(other)


class AgencyMiddleMixin(object):
    '''Responsible for formating messages, calling methods etc'''

    guid = None

    protocol_id = None
    remote_id = None

    error_state = None

    def __init__(self, remote_id=None, protocol_id=None):
        self.guid = str(uuid.uuid1())
        self._set_remote_id(remote_id)
        self._set_protocol_id(protocol_id)

    def is_idle(self):
        return False

    def _set_remote_id(self, remote_id):
        if self.remote_id is not None and self.remote_id != remote_id:
            self.debug('Changing id of remote peer. %r -> %r. '
                       'This usually means the message has been handed over.',
                       self.remote_id, remote_id)
        self.remote_id = remote_id

    def _set_protocol_id(self, protocol_id):
        self.protocol_id = protocol_id

    def _send_message(self, msg, expiration_time=None, recipients=None,
                      remote_id=None):
        msg.sender_id = self.guid
        msg.receiver_id = remote_id or self.remote_id
        msg.protocol_id = self.protocol_id
        if msg.expiration_time is None:
            if expiration_time is None:
                expiration_time = time.future(10)
            msg.expiration_time = expiration_time

        if not recipients:
            recipients = self.recipients

        return self.agent.send_msg(recipients, msg)

    def _handover_message(self, msg, remote_id=None):
        msg.receiver_id = remote_id or self.remote_id
        return self.agent.send_msg(self.recipients, msg)

    def _call(self, method, *args, **kwargs):
        '''Call the method, wrap it in Deferred and bind error handler'''
        d = defer.maybeDeferred(method, *args, **kwargs)
        d.addErrback(self._error_handler)
        return d

    def _error_handler(self, f):
        if f.check(FiberCancelled):
            self._terminate(ProtocolFailed("Fiber was cancelled because "
                        "the state of the medium changed. This happens "
                        "when constructing a fiber with a canceller."))

        error_handler(self, f)
        self._set_state(self.error_state)
        self._terminate(f)


class ExpirationCallsMixin(object):
    '''
    Mixin class used by protocol peers for protecting execution time with
    timeout.
    '''

    agent = None
    factory = None

    def __init__(self):
        self._expiration_call = None

    @replay.side_effect
    def get_expiration_time(self):
        if self._expiration_call:
            return self._expiration_call.getTime()

    def _get_time(self):
        raise NotImplemented('Should be define in the class using the mixin')

    def _setup_expiration_call(self, expire_time, state,
                               method, *args, **kwargs):
        self.log('Setting expiration call of method: %r.%r',
                 self.__class__.__name__, method.__name__)

        time_left = time.left(expire_time)
        if time_left < 0:
            raise RuntimeError('Tried to call method in the past! ETA: %r' %
                               (time_left, ))

        def to_call(callback):
            if state:
                self._set_state(state)
            self.log('Calling method: %r with args: %r', method, args)
            d = defer.maybeDeferred(method, *args, **kwargs)
            d.addErrback(self._error_handler)
            d.addCallback(callback.callback)

        result = defer.Deferred()
        self._expiration_call = time.callLater(
            time_left, to_call, result)
        return result

    def _expire_at(self, expire_time, state, method, *args, **kwargs):

        def expired(param):
            return self._terminate(self._create_expired_error(param))

        d = self._setup_expiration_call(expire_time, state,
                                        method, *args, **kwargs)
        d.addCallback(expired)
        return d

    @replay.side_effect
    def _cancel_expiration_call(self):
        if self._expiration_call and self._expiration_call.active():
            self.log('Canceling expiration call')
            self._expiration_call.cancel()
            self._expiration_call = None

    def _terminate(self):
        self._cancel_expiration_call()

    def expire_now(self):
        if self._expiration_call and self._expiration_call.active():
            self._expiration_call.reset(0)
            d = self.notify_finish()
            return d

        self.error('Expiration call %r is None or was already called '
                   'or cancelled', self._expiration_call)

        return defer.fail(self._create_expired_error("Forced expiration"))

    def _create_expired_error(self, msg):

        def get_type_name(obj):
            return obj.type_name if obj is not None else "unknown"

        cause = None

        if isinstance(msg, failure.Failure):
            cause = msg
            msg = error.get_failure_message(msg)
        elif msg is not None:
            msg = str(msg)

        factory = self.factory
        pname = factory.type_name if factory is not None else "unknown"
        agent = self.agent.get_agent() if self.agent is not None else None
        aname = agent.descriptor_type if agent is not None else "unknown"
        aid = self.agent.get_agent_id() if self.agent is not None else None

        error_msg = "%s agent %s's protocol %s expired" % (aname, aid, pname)
        if msg is not None:
            error_msg += ": %s" % (msg, )

        return ProtocolExpired(error_msg, cause=cause)


class InitiatorMediumBase(object):

    def _terminate(self):
        '''Nothing special.'''


class TransientInitiatorMediumBase(InitiatorMediumBase):

    def __init__(self):
        self._fnotifier = defer.Notifier()

    @serialization.freeze_tag('IAgencyProtocol.notify_finish')
    def notify_finish(self):
        #FIXME: Should fail if already terminated
        return self._fnotifier.wait('finish')

    def _terminate(self, result):
        if isinstance(result, (failure.Failure, Exception)):
            self.log("Firing errback of notifier with result: %r.", result)
            self.call_next(self._fnotifier.errback, 'finish', result)
        else:
            self.log("Firing callback of notifier with result: %r.", result)
            self.call_next(self._fnotifier.callback, 'finish', result)


class InterestedMediumBase(object):

    def _terminate(self):
        '''Nothing special.'''


class TransientInterestedMediumBase(InterestedMediumBase):

    def __init__(self):
        self._fnotifier = defer.Notifier()

    def _terminate(self, result):
        self.call_next(self._fnotifier.callback, 'finish', result)

    @serialization.freeze_tag('IAgencyProtocol.notify_finish')
    def notify_finish(self):
        return self._fnotifier.wait('finish')

    def call_next(self, *_):
        raise NotImplementedError("This method should be implemented outside "
                                  "of this mixin!")


@serialization.register
class Observer(observer.Observer):
    classProvides(IRestorator)

    active = replay.side_effect(observer.Observer.active)
    get_result = replay.side_effect(observer.Observer.get_result)

    def notify_finish(self):
        return fiber.wrap_defer(observer.Observer.notify_finish, self)


class ConnectionState(enum.Enum):

    connected, disconnected = range(2)


class ConnectionManager(StateMachineMixin):
    '''
    Base for classes having connected/disconnected state. Exposes methods
    to change the state and register callbacks.
    '''

    def __init__(self):
        StateMachineMixin.__init__(self, ConnectionState.disconnected)
        self._disconnected_cbs = list()
        self._reconnected_cbs = list()

    def add_disconnected_cb(self, method):
        self._check_callable(method)
        self._disconnected_cbs.append(method)

    def add_reconnected_cb(self, method):
        self._check_callable(method)
        self._reconnected_cbs.append(method)

    def wait_connected(self):
        return self.wait_for_state(ConnectionState.connected)

    def is_connected(self):
        return self._cmp_state(ConnectionState.connected)

    def _on_connected(self):
        if self._cmp_state(ConnectionState.disconnected):
            self._set_state(ConnectionState.connected)
            return self._notify(self._reconnected_cbs)

    def _on_disconnected(self):
        if self._cmp_state(ConnectionState.connected):
            self._set_state(ConnectionState.disconnected)
            return self._notify(self._disconnected_cbs)

    def _notify(self, callbacks):
        defers = map(lambda cb: defer.maybeDeferred(cb), callbacks)
        return defer.DeferredList(defers, consumeErrors=True)

    def _check_callable(self, method):
        if not callable(method):
            raise AttributeError("Expected callable, got %r" % method)


class Procedure(log.Logger, StateMachineMixin, mro.DeferredMroMixin):

    stages = None

    def __init__(self, friend, **opts):
        if self.stages is None:
            raise NotImplementedError("stages attribute needs to be set")

        log.Logger.__init__(self, friend)
        initial_state = first(iter(self.stages))
        StateMachineMixin.__init__(self, initial_state)

        self.friend = friend
        self.opts = opts
        self._observer = observer.Observer(self._initiate)

    ### public methods ###

    def initiate(self):
        return self._observer.initiate()

    def reentrant_call(self, **opts):
        self.debug('%s called in reentrant way in stage: %r',
                   type(self).__name__, self.state)
        if opts != self.opts:
            self.debug('Reconfiguring %r -> %r', self.opts, opts)
            self.opts = opts
        return self._observer.notify_finish()

    ### private ###

    def _initiate(self):
        d = defer.succeed(None)
        for stage in self.stages:
            method_name = "stage_%s" % (stage.name, )

            d.addBoth(self._print_log, stage)
            d.addBoth(defer.drop_param, self._set_state, stage)
            d.addBoth(defer.drop_param, self.call_mro, method_name)
        return d

    def _print_log(self, param, stage):
        self.log('Entering stage %s. Defer result at this point: %r',
                 stage.name, param)
        if isinstance(param, failure.Failure):
            error.handle_failure(self, param, 'Failure in previous stage: ')
