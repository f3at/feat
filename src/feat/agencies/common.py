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
from feat.interface.fiber import ICancellable
from feat.interface.log import LogLevel
from twisted.python import failure

from feat.common import log, defer, fiber, observer, time, enum
from feat.common import serialization, mro, error, first
from feat.agents.base import replay

from feat.interface.protocols import ProtocolExpired, ProtocolFailed
from feat.interface.serialization import IRestorator
from feat.agencies.interface import IAgencyProtocolInternal


class Statistics(object):

    def __init__(self):
        self._statistics = dict()

    def increase_stat(self, key, value=1):
        if key not in self._statistics:
            self._statistics[key] = 0
        self._statistics[key] += value

    def get_stats(self):
        return self._statistics.items()


class StateAssertationError(Exception):
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
            fireOnOneCallback=True, fireOnOneErrback=True,
            consumeErrors=True)
        d.addCallback(lambda _: self)
        return d

    def _set_state(self, state):
        if not self.state or not (state == self.state):
            self.log('Changing state from %r to %r', self.state, state)
            self.state = state

        if self._notifier:
            time.call_next(self._notifier.callback, state, self)

    def _cmp_state(self, states):
        if not isinstance(states, (list, tuple, )):
            states = [states]
        return self.state in states

    def _ensure_state(self, states):
        if self._cmp_state(states):
            return True
        self.debug("Expected state in: %r, was: %r instead",
                   states, self.state)
        return False

    def _get_machine_state(self):
        return self.state

    def _event_handler(self, mapping, event):
        klass = event.__class__
        decision = mapping.get(klass, None)
        if not decision:
            self.warning("Unknown event received %r. Ignoring", event)
            return

        if isinstance(decision, list):
            match = filter(
                lambda x: self._cmp_state(x['state_before']), decision)
            if len(match) != 1:
                self.warning("Expected to find excatly one handler for %r in "
                             "state %r, found %r handlers", event,
                             self._get_machine_state(),
                             len(match))
                return
            decision = match[0]

        state_before = decision['state_before']
        if not self._ensure_state(state_before):
            self.warning("Received event: %r in state: %r, expected state "
                         "for this method is: %r",
                         klass, self._get_machine_state(),
                         decision['state_before'])
            return

        state_after = decision['state_after']
        self._set_state(state_after)
        return decision['method']

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


class AgencyMiddleBase(log.LogProxy, log.Logger, StateMachineMixin):
    '''Responsible for formating messages, calling methods etc'''

    error_state = None

    implements(IAgencyProtocolInternal)

    def __init__(self, agency_agent, factory,
                 remote_id=None, protocol_id=None):
        log.Logger.__init__(self, agency_agent)
        log.LogProxy.__init__(self, agency_agent)
        StateMachineMixin.__init__(self)


        self.agent = agency_agent
        self.factory = factory

        self.guid = str(uuid.uuid1())
        self.set_remote_id(remote_id)
        self.set_protocol_id(protocol_id)

        # List of references to currently performed agent-side jobs.
        self._agent_jobs = list()

        self._finalize_called = False
        self._fnotifier = defer.Notifier()

        self._timeout_call = None

    ### IAgencyProtocolInternal ###

    @serialization.freeze_tag('IAgencyProtocol.notify_finish')
    def notify_finish(self):
        if self._finalize_called:
            if isinstance(self._result, (Exception, failure.Failure)):
                return defer.fail(self._result)
            else:
                return defer.succeed(self._result)
        return self._fnotifier.wait('finish')

    def is_idle(self):
        return len(self._agent_jobs) == 0 and (self._timeout_call is None or
                                               not self._timeout_call.active())

    def cleanup(self):
        self.cancel_timeout()
        self.cancel_agent_jobs()

        if not self._finalize_called:
            self.finalize(self.create_expired_error())

    def get_agent_side(self):
        raise NotImplementedError("should be implemented in the child class")

    ### public ###

    def cancel_agent_jobs(self):
        l = self._agent_jobs
        self._agent_jobs = list()
        for d in l:
            d.cancel()

    def cancel_timeout(self):
        if self._timeout_call and self._timeout_call.active():
            self._timeout_call.cancel()
        self._timeout_call = None

    def set_timeout(self, expiration_time, state, callback, *args, **kwargs):
        self.cancel_timeout()
        eta = max([0, time.left(expiration_time)])
        self._timeout_call = time.call_later(
            eta, self._timeout_target, state, callback, args, kwargs)

    @replay.side_effect
    def get_expiration_time(self):
        if self._timeout_call:
            return self._timeout_call.getTime()

    def call_agent_side(self, method, *args, **kwargs):
        '''
        Call the method, wrap it in Deferred and bind error handler.
        '''
        assert not self._finalize_called, ("Attempt to call agent side code "
                                           "after finalize() method has been "
                                           "called. Method: %r" % (method, ))

        ensure_state = kwargs.pop('ensure_state', None)


        d = defer.Deferred(canceller=self._cancel_agent_side_call)
        self._agent_jobs.append(d)
        if ensure_state:
            # call method only if state check is checks in
            d.addCallback(
                lambda _: (self._ensure_state(ensure_state) and
                           method(*args, **kwargs)))
        else:
            d.addCallback(defer.drop_param, method, *args, **kwargs)
        d.addErrback(self._error_handler, method)
        d.addBoth(defer.bridge_param, self._remove_agent_job, d)
        time.call_next(d.callback, None)
        return d

    def create_expired_error(self, msg="Forced expiration"):
        factory = self.factory
        pname = factory.type_name if factory is not None else "unknown"
        agent = self.agent.get_agent() if self.agent is not None else None
        aname = agent.descriptor_type if agent is not None else "unknown"
        aid = self.agent.get_agent_id() if self.agent is not None else None
        error_msg = "%s agent %s's protocol %s expired" % (aname, aid, pname)
        if msg:
            error_msg += ": " + msg
        return ProtocolExpired(error_msg)

    def finalize(self, result):
        if self._finalize_called:
            return
        self._finalize_called = True
        self._result = result

        if isinstance(result, (failure.Failure, Exception)):
            self.log("Firing errback of notifier with result: %r.", result)
            time.call_next(self._fnotifier.errback, 'finish', result)
        else:
            self.log("Firing callback of notifier with result: %r.",
                     result)
            time.call_next(self._fnotifier.callback, 'finish', result)
        self.cleanup()

    ### specific to sending messages ###

    def set_remote_id(self, remote_id):
        if hasattr(self, 'remote_id') and self.remote_id != remote_id:
            self.debug('Changing id of remote peer. %r -> %r. '
                       'This usually means the message has been handed over.',
                       self.remote_id, remote_id)
        self.remote_id = remote_id

    def set_protocol_id(self, protocol_id):
        self.protocol_id = protocol_id

    def send_message(self, msg, expiration_time=None, recipients=None,
                      remote_id=None):
        msg.sender_id = self.guid
        msg.receiver_id = remote_id or self.remote_id
        msg.protocol_id = self.protocol_id
        if msg.expiration_time is None:
            if expiration_time is None:
                expiration_time = time.future(10)
            msg.expiration_time = expiration_time

        if not recipients and getattr(self, 'recipients') is not None:
            recipients = self.recipients

        return self.agent.send_msg(recipients, msg)

    def handover_message(self, msg, remote_id=None):
        msg.receiver_id = remote_id or self.remote_id
        return self.agent.send_msg(self.recipients, msg)

    ### private ###

    def _cancel_agent_side_call(self, d):
        d._suppressAlreadyCalled = True
        d.errback(failure.Failure(self.create_expired_error("")))

    def _run_and_terminate(self, method, *args, **kwargs):
        d = self.call_agent_side(method, *args, **kwargs)
        d.addBoth(ProtocolFailed)
        d.addCallback(self.finalize)
        return d

    def _timeout_target(self, state, callback, args, kwargs):
        if state:
            self._set_state(state)
        self.call_agent_side(callback, *args, ensure_state=state,
                             **kwargs)

    def _remove_agent_job(self, d):
        try:
            self._agent_jobs.remove(d)
        except:
            # this might happen because of race condition between the
            # remove_agent_job() and cancel_agent_jobs() calls
            pass

    def _error_handler(self, f, method):
        if f.check(defer.CancelledError, ProtocolExpired):
            # this is what happens when the call is cancelled by the
            # _call() method, just swallow it
            pass
        else:
            error.handle_failure(self, f, "Failed calling agent method %r",
                                 method)
            self._set_state(self.error_state)
            self.finalize(f)


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
        self._failures = []

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

    def notify_finish(self):
        return self._observer.notify_finish()

    ### private ###

    def _initiate(self):
        d = defer.succeed(None)
        for stage in self.stages:
            method_name = "stage_%s" % (stage.name, )

            d.addBoth(defer.drop_param, self.log, "Entering stage %s",
                      stage.name)
            d.addBoth(defer.drop_param, self._set_state, stage)
            d.addBoth(defer.drop_param, self.call_mro, method_name)
            d.addBoth(self._print_log, stage)
        d.addBoth(self._format_result)
        return d

    def _format_result(self, _res):
        # if any of the stages failed return the first failure as the result
        if self._failures:
            return self._failures[0]

    def _print_log(self, param, stage):
        self.log('Finished stage %s. Defer result at this point: %r',
                 stage.name, param)
        if isinstance(param, failure.Failure):
            error.handle_failure(self, param, 'Failure in stage %s: ',
                                 stage.name)
            self._failures.append(param)
