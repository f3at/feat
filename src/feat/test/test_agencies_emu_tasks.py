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
from feat.agents.base import descriptor, replay, task
from feat.agencies.tasks import TaskState, NOT_DONE_YET
from feat.agencies import retrying
from feat.common import defer
from feat.interface import protocols

from feat.test import common


class SomeException(Exception):
    pass


class BaseTestTask(task.BaseTask, common.Mock):

    def __init__(self, *args, **kwargs):
        task.BaseTask.__init__(self, *args, **kwargs)
        common.Mock.__init__(self)

    @replay.immutable
    def _get_medium(self, state):
        return state.medium


class AsyncTask(BaseTestTask):

    @replay.entry_point
    def initiate(self, state):
        return NOT_DONE_YET

    @replay.mutable
    def terminate(self, state, arg):
        state.medium.terminate(arg)

    @replay.mutable
    def fail(self, state, arg):
        state.medium.fail(arg)


class TimeoutTask(BaseTestTask):

    protocol_id = 'timeout-task'
    timeout = 1

    def __init__(self, *args, **kwargs):
        BaseTestTask.__init__(self, *args, **kwargs)

    @common.Mock.stub
    def expired(self):
        pass

    @common.Mock.record
    def initiate(self):
        d = defer.Deferred()
        return d


class DummyException(Exception):
    pass


class ErrorTask(BaseTestTask):

    protocol_id = 'error-task'

    def __init__(self, *args, **kwargs):
        BaseTestTask.__init__(self, *args, **kwargs)

    @common.Mock.record
    def initiate(self):
        raise DummyException('ErrorTask')


class SuccessTask(BaseTestTask):

    protocol_id = 'success-task'

    def __init__(self, *args, **kwargs):
        BaseTestTask.__init__(self, *args, **kwargs)

    @common.Mock.stub
    def initiate(self):
        pass


@common.attr(timescale=0.05)
class TestTask(common.TestCase, common.AgencyTestHelper):

    protocol_type = "Task"

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        yield common.AgencyTestHelper.setUp(self)
        desc = yield self.doc_factory(descriptor.Descriptor)
        self.agent = yield self.agency.start_agent(desc)
        self.finished = None

    def start_task(self, t):
        self.task = self.agent.initiate_protocol(t)
        self.finished = self.task.notify_finish()

    def tearDown(self):
        return self.finished

    def assertState(self, state):
        self.assertEqual(state, self.task._get_medium().state)

    def assertTimeout(self):
        self.assertState(TaskState.expired)
        self.assertCalled(self.task, 'expired', times=1)

    @defer.inlineCallbacks
    def testInitiateTimeout(self):
        self.start_task(TimeoutTask)
        self.assertFailure(self.finished, protocols.ProtocolExpired)
        yield self.finished
        self.assertTimeout()

    @defer.inlineCallbacks
    def testInitiateError(self):
        self.start_task(ErrorTask)
        self.assertFailure(self.finished, DummyException)
        yield self.finished
        self.assertState(TaskState.error)

    @defer.inlineCallbacks
    def testInitiateSuccess(self):
        self.start_task(SuccessTask)
        yield self.finished
        self.assertState(TaskState.completed)

    @defer.inlineCallbacks
    def testWaitForState(self):
        self.start_task(TimeoutTask)
        yield self.task._get_medium().wait_for_state(TaskState.expired)
        self.assertFailure(self.finished, protocols.ProtocolExpired)
        self.assertEqual(TaskState.expired, self.task._get_medium().state)

    @defer.inlineCallbacks
    def testRetryingProtocol(self):
        d = self.cb_after(None, self.agent, 'initiate_protocol')
        factory = retrying.RetryingProtocolFactory(ErrorTask, max_retries=3)
        task = self.agent.initiate_protocol(factory)
        self.finished = task.notify_finish()
        yield d
        self.assertEqual(task.attempt, 1)
        yield self.cb_after(None, self.agent, 'initiate_protocol')
        yield self.cb_after(None, self.agent, 'initiate_protocol')
        yield self.cb_after(None, self.agent, 'initiate_protocol')
        self.assertEqual(task.attempt, task.max_retries+1)
        self.assertFailure(self.finished, DummyException)

    @defer.inlineCallbacks
    def testAsyncTasks(self):
        self.start_task(AsyncTask)
        self.assertFalse(self.task.finished())
        d = self.task.notify_finish()
        self.task.terminate('result')
        res = yield d
        self.assertEqual('result', res)
        self.assertTrue(self.task.finished())

        self.start_task(AsyncTask)
        self.assertFailure(self.finished, SomeException)
        self.task.fail(SomeException('result'))
        yield self.finished
