# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.internet import defer

from feat.agents.base import (descriptor, replay, task)
from feat.agencies.tasks import TaskState, NOT_DONE_YET
from feat.common import serialization
from feat.interface import protocols

from feat.test import common


@serialization.register
class SomeException(Exception, serialization.Serializable):
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
    def finish(self, state, arg):
        state.medium.finish(arg)

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


class ErrorTask(BaseTestTask):

    protocol_id = 'error-task'

    def __init__(self, *args, **kwargs):
        BaseTestTask.__init__(self, *args, **kwargs)

    @common.Mock.record
    def initiate(self):
        raise BaseException('ErrorTask')


class SuccessTask(BaseTestTask):

    protocol_id = 'success-task'

    def __init__(self, *args, **kwargs):
        BaseTestTask.__init__(self, *args, **kwargs)

    @common.Mock.stub
    def initiate(self):
        pass


class TestTask(common.TestCase, common.AgencyTestHelper):

    protocol_type = "Task"

    @defer.inlineCallbacks
    def setUp(self):
        common.AgencyTestHelper.setUp(self)
        desc = yield self.doc_factory(descriptor.Descriptor)
        self.agent = yield self.agency.start_agent(desc)
        self.finished = None

    def start_task(self, t):
        self.task = \
                self.agent.initiate_task(t)
        self.finished = self.task.notify_finish()

    def tearDown(self):
        return self.finished

    def assertState(self, _, state):
        self.assertFalse(self.task._get_medium().session_id in \
                self.agent._listeners)
        self.assertEqual(state, self.task._get_medium().state)
        return self.finished

    def assertTimeout(self, _):
        self.assertState(_, TaskState.expired)
        self.assertCalled(self.task, 'expired', times=1)

    def testInitiateTimeout(self):
        self.start_task(TimeoutTask)
        d = self.cb_after(arg=None, obj=self.task._get_medium(),
                          method="_terminate")
        d.addCallback(self.assertTimeout)
        self.assertFailure(self.finished, protocols.InitiatorExpired)
        return d

    def testInitiateError(self):
        self.start_task(ErrorTask)
        d = self.cb_after(arg=None, obj=self.agent,
                          method="unregister_listener")
        d.addCallback(self.assertState, TaskState.error)
        self.assertFailure(self.finished, BaseException)
        return d

    def testInitiateSuccess(self):
        self.start_task(SuccessTask)
        d = self.cb_after(arg=None, obj=self.agent,
                          method="unregister_listener")
        d.addCallback(self.assertState, TaskState.completed)
        return d

    @defer.inlineCallbacks
    def testWaitForState(self):
        self.start_task(TimeoutTask)
        yield self.task._get_medium().wait_for_state(TaskState.expired)
        self.assertFailure(self.finished, protocols.InitiatorExpired)
        self.assertEqual(TaskState.expired, self.task._get_medium().state)

    @defer.inlineCallbacks
    def testRetryingProtocol(self):
        d = self.cb_after(None, self.agent, 'initiate_protocol')
        task = self.agent.retrying_task(ErrorTask, max_retries=3)
        self.finished = task.notify_finish()
        yield d
        self.assertEqual(task.attempt, 1)
        yield self.cb_after(None, self.agent, 'initiate_protocol')
        yield self.cb_after(None, self.agent, 'initiate_protocol')
        yield self.cb_after(None, self.agent, 'initiate_protocol')
        self.assertEqual(task.attempt, task.max_retries+1)
        self.assertFailure(self.finished, BaseException)

    @defer.inlineCallbacks
    def testAsyncTasks(self):
        self.start_task(AsyncTask)
        self.assertFalse(self.task.finished())
        d = self.task.notify_finish()
        self.task.finish('result')
        res = yield d
        self.assertEqual('result', res)
        self.assertTrue(self.task.finished())

        self.start_task(AsyncTask)
        self.assertFailure(self.finished, SomeException)
        self.task.fail(SomeException('result'))
        yield self.finished
