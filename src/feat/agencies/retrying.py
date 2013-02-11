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
from zope.interface import implements
from twisted.python.failure import Failure

from feat.agents.base import replay
from feat.common import log, defer, serialization, time

from feat.agencies.interface import (IAgencyInitiatorFactory,
                                     ILongRunningProtocol)
from feat.interface.serialization import ISerializable
from feat.interface.protocols import IInitiatorFactory


@serialization.register
class RetryingProtocolFactory(serialization.Serializable):

    implements(IInitiatorFactory, IAgencyInitiatorFactory)

    type_name="retrying-protocol-factory"

    protocol_type = "Special"

    def __init__(self, factory, max_retries=None,
                 initial_delay=1, max_delay=None, busy=True,
                 alert_after=None, alert_service=None):
        self.protocol_id = "retried-" + factory.protocol_id
        self.factory = factory
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.busy = busy
        self.alert_after = alert_after
        self.alert_service = alert_service

    def __call__(self, agency_agent, *args, **kwargs):
        return RetryingProtocol(agency_agent, self.factory,
                                args, kwargs,
                                max_retries=self.max_retries,
                                initial_delay=self.initial_delay,
                                max_delay=self.max_delay,
                                busy=self.busy,
                                alert_after=self.alert_after,
                                alert_service=self.alert_service)

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return (self.__dict__ == other.__dict__)

    def __ne__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return (self.__dict__ != other.__dict__)


class RetryingProtocol(log.Logger):

    implements(ISerializable, ILongRunningProtocol)

    type_name="retrying-protocol"

    protocol_type = "Special"

    def __init__(self, agency_agent, factory, args=None, kwargs=None,
                 max_retries=None, initial_delay=1, max_delay=None, busy=True,
                 alert_after=None, alert_service=None):
        log.Logger.__init__(self, agency_agent)

        self.protocol_id = "retried-" + factory.protocol_id

        self.medium = agency_agent
        self.factory = factory
        self.args = args or ()
        self.kwargs = kwargs or {}

        self.max_retries = max_retries
        self.max_delay = max_delay
        self.attempt = 0
        self.delay = initial_delay
        self.busy = busy # If the protocol should not be idle between retries
        self.alert_after = alert_after
        self.alert_service = alert_service

        # check that agent supports raising alerts
        if self.alert_after and \
           (not hasattr(self.medium.agent, 'raise_alert') or
            not hasattr(self.medium.agent, 'resolve_alert')):
            self.warning("Retrying protocol was asked to raise an alert in "
                         "case of %d failed attempts. However the agent does "
                         "not mixin in alert.AgentMixin. This functionality "
                         "will be disabled.", self.alert_after)
            self.alert_after = None
        if ((self.alert_after is not None and self.alert_service is None) or
            (self.alert_after is None and self.alert_service is not None)):
            raise ValueError("Both or none of alert_after and alert_service "
                             "options needs to be specified")

        self._delayed_call = None
        self._initiator = None

        self._fnotifier = defer.Notifier()

    ### Public Methods ###

    def initiate(self):
        time.call_next(self._bind)
        return self

    def call_later(self, _time, _method, *args, **kwargs):
        return self.medium.call_later_ex(_time, _method, args, kwargs,
                                         busy=self.busy)

    @replay.named_side_effect('RetryingProtocol.get_status')
    def get_status(self):
        res = dict()
        res['attempt'] = self.attempt
        res['max_retries'] = self.max_retries
        res['delay'] = self.delay
        res['running_now'] = self._initiator is not None
        return res

    ### ILongRunningProtocol Methods ###

    @serialization.freeze_tag('IAgencyProtocol.notify_finish')
    def notify_finish(self):
        msg = "notify_finish() called after finalizing the RetryingProtocol"
        assert self._fnotifier is not None, msg
        return self._fnotifier.wait('finish')

    @serialization.freeze_tag('RetryingProtocol.cancel')
    def cancel(self):
        self.max_retries = self.attempt - 1
        if self._delayed_call:
            self.medium.cancel_delayed_call(self._delayed_call)
            self._delayed_call = None
            return defer.succeed(None)
        if self._fnotifier:
            self._fnotifier.cancel('finish')
            self._fnotifier = None
        if self._initiator:
            #FIXME: we shouldn't have to use _get_state()
            self._initiator._get_state().medium.cleanup()

    def is_idle(self):
        if self._initiator is not None:
            return self._initiator.is_idle()
        return not self.busy

    ### ISerializable Methods ###

    def snapshot(self):
        return id(self)

    ### Private Methods ###

    def _bind(self):
        d = self._fire()
        d.addCallbacks(self._finalize, self._wait_and_retry)

    def _fire(self):
        self.attempt += 1
        self._initiator = self.medium.initiate_protocol(self.factory,
                                                        *self.args,
                                                        **self.kwargs)
        d = self._initiator.notify_finish()
        return d

    def _finalize(self, result):
        # check if we should resolve an alert
        if self.alert_after is not None and self.attempt > self.alert_after:
            self.medium.agent.resolve_alert(self.alert_service)

        self._trigger_callbacks(result)

    def _trigger_callbacks(self, result):
        if not self._fnotifier:
            return
        if isinstance(result, (Failure, Exception)):
            self.log("Firing errback of notifier with result: %r.", result)
            time.call_next(self._fnotifier.errback, 'finish', result)
        else:
            self.log("Firing callback of notifier with result: %r.", result)
            time.call_next(self._fnotifier.callback, 'finish', result)
        self._fnotifier = None

    def _wait_and_retry(self, failure):
        self.info('Retrying failed for the %d time with %s %s factory %r',
                  self.attempt, self.medium.agent.descriptor_type,
                  self.medium.get_full_id(), self.factory)

        self._initiator = None

        # check if we should raise an alert
        if self.alert_after is not None and self.attempt >= self.alert_after:
            self.info("I will raise an alert.")
            self.medium.agent.raise_alert(self.alert_service)

        # check if we are done
        if self.max_retries is not None and self.attempt > self.max_retries:
            self.info("Will not try to restart.")
            self._trigger_callbacks(failure)
            return

        # do retry
        self.info('Will retry in %d seconds', self.delay)
        self._delayed_call = self.call_later(self.delay, self._bind)

        # adjust the delay
        if self.max_delay is None:
            self.delay *= 2
        elif self.delay < self.max_delay:
            self.delay = min((2 * self.delay, self.max_delay, ))
