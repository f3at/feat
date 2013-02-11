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
# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.internet import defer

from feat.common import log, time
from feat.agencies import retrying
from feat.agents.base import task

from . import common


class DummyAgent(object):

    def __init__(self):
        self.descriptor_type = "dummy-agent"
        self.alert_actions = list()

    def raise_alert(self, service):
        assert service == 'test', service
        self.alert_actions.append('raise')

    def resolve_alert(self, service):
        assert service == 'test', service
        self.alert_actions.append('resolve')


class CallLaterMixin(object):

    def call_later_ex(self, _time, _method, args=None, kwargs=None, busy=True):
        args = args or ()
        kwargs = kwargs or {}
        return time.callLater(_time, _method, *args, **kwargs)

    def call_later(self, _time, _method, *args, **kwargs):
        return self.call_later_ex(_time, _method, args, kwargs)

    def call_next(self, _method, *args, **kwargs):
        self.call_later_ex(0, _method, args, kwargs)

    def cancel_delayed_call(self, call_id):
        if call_id.active():
            call_id.cancel()


class DummyRepeatMedium(common.Mock, CallLaterMixin,
                        log.Logger, log.LogProxy):

    def __init__(self, testcase, success_at_try=None):
        log.Logger.__init__(self, testcase)
        log.LogProxy.__init__(self, testcase)

        self.number_called = 0
        self.success_at_try = success_at_try

        self.agent = DummyAgent()

    def get_full_id(self):
        return "dummy-medium"

    def initiate_protocol(self, factory, *args, **kwargs):
        self.number_called += 1
        self.info('called %d time', self.number_called)
        if self.success_at_try is not None and\
            self.success_at_try < self.number_called:
            return factory(True)
        else:
            return factory(False)


class DummyInitiator(common.Mock):

    protocol_type = "Dummy"
    protocol_id = "dummy"

    def __init__(self, should_work):
        self.should_work = should_work

    def notify_finish(self):
        if self.should_work:
            return defer.succeed(None)
        else:
            return defer.fail(RuntimeError())


class DummySyncTask(object):

    protocol_type = "Task"
    protocol_id = "dummy-sync-task"

    def __init__(self, agent, medium):
        self.agent = agent
        self.medium = medium

    def initiate(self):
        self.medium.external_counter += 1

    def notify_finish(self):
        return defer.succeed(self)


class DummyAsyncTask(object):

    protocol_type = "Task"
    protocol_id = "dummy-async-task"

    def __init__(self, agent, medium):
        self.agent = agent
        self.medium = medium
        self.finish = defer.Deferred()

    def initiate(self):
        self.medium.external_counter += 1
        time.callLater(2, self.finish.callback, self)
        return task.NOT_DONE_YET

    def notify_finish(self):
        return self.finish


class DummyPeriodicalMedium(common.Mock, CallLaterMixin,
                            log.Logger, log.LogProxy):

    def __init__(self, testcase, success_at_try=None):
        log.Logger.__init__(self, testcase)
        log.LogProxy.__init__(self, testcase)

        self.agent = DummyAgent()

        self.external_counter = 0
        self.internal_counter = 0

        self.current = None

    def get_full_id(self):
        return "dummy-medium"

    def initiate_protocol(self, factory, *args, **kwargs):
        assert self.current is None
        self.internal_counter += 1
        f = factory(self.agent, self)
        self.current = f
        f.initiate(*args, **kwargs)
        d = f.notify_finish()
        d.addCallback(self._finished)
        return f

    def _finished(self, _):
        self.current = None


@common.attr(timescale=0.05)
class TestRetryingProtocol(common.TestCase):

    timeout = 20

    configurable_attributes = common.TestCase.configurable_attributes +\
                              ['success_at_try']
    success_at_try = None

    def setUp(self):
        self.medium = DummyRepeatMedium(self, self.success_at_try)
        return common.TestCase.setUp(self)

    @defer.inlineCallbacks
    def testRetriesForever(self):
        d = self.cb_after(None, self.medium, 'initiate_protocol')
        instance = self._start_instance(None, 1, None)
        yield d
        yield self.cb_after(None, self.medium, 'initiate_protocol')
        yield self.cb_after(None, self.medium, 'initiate_protocol')
        yield self.cb_after(None, self.medium, 'initiate_protocol')
        yield self.cb_after(None, self.medium, 'initiate_protocol')
        instance.cancel()
        self.assertEqual(5, self.medium.number_called)

    @defer.inlineCallbacks
    @common.attr(success_at_try=2)
    def testRaisingAndResolvingAlert(self):
        instance = self._start_instance(None, 1, None, 1)
        yield instance.notify_finish()
        self.assertEqual(3, self.medium.number_called)
        self.assertEqual(3, len(self.medium.agent.alert_actions))
        self.assertEqual('raise', self.medium.agent.alert_actions[0])
        self.assertEqual('raise', self.medium.agent.alert_actions[1])
        self.assertEqual('resolve', self.medium.agent.alert_actions[2])

    @defer.inlineCallbacks
    def testMaximumNumberOfRetries(self):
        instance = self._start_instance(3, 1, None)
        d = instance.notify_finish()
        self.assertFailure(d, RuntimeError)
        yield d
        self.assertEqual(4, self.medium.number_called)
        self.assertEqual(8, instance.delay)

    @defer.inlineCallbacks
    def testMaximumDelay(self):
        instance = self._start_instance(3, 1, 2)
        d = instance.notify_finish()
        self.assertFailure(d, RuntimeError)
        yield d
        self.assertEqual(4, self.medium.number_called)
        self.assertEqual(2, instance.delay)

    def _start_instance(self, max_retries, initial_delay, max_delay,
                        alert_after=None):
        if alert_after is not None:
            alert_service = 'test'
        else:
            alert_service = None

        instance = retrying.RetryingProtocol(
            self.medium, DummyInitiator, max_retries=max_retries,
            initial_delay=initial_delay, max_delay=max_delay,
            alert_after=alert_after, alert_service=alert_service)
        return instance.initiate()
