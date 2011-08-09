# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from feat.agents.base import descriptor, replay, message, recipient
from feat.agents.base import collector, poster
from feat.common import defer

from feat.interface.protocols import *
from feat.interface.collector import *

from . import common


class DummyCollector(collector.BaseCollector, common.Mock):

    protocol_id = 'dummy-notification'
    interest_type = InterestType.public

    def __init__(self, agent, medium):
        collector.BaseCollector.__init__(self, agent, medium)
        common.Mock.__init__(self)
        self.result = None
        self.max = 0
        self.curr = 0
        self.total = 0

    @replay.immutable
    def _get_medium(self, state):
        return state.medium

    @common.Mock.record
    def notified(self, message):
        return self.result


class DummyConcurrentCollector(collector.BaseCollector, common.Mock):

    protocol_id = 'dummy-notification'
    interest_type = InterestType.public
    concurrency = 5

    def __init__(self, agent, medium):
        collector.BaseCollector.__init__(self, agent, medium)
        common.Mock.__init__(self)
        self.max = 0
        self.curr = 0
        self.total = 0

    @replay.immutable
    def _get_medium(self, state):
        return state.medium

    @common.Mock.record
    def notified(self, message):
        self.curr += 1
        self.total += 1
        if self.curr > self.max:
            self.max = self.curr

        d = common.delay(None, 1)
        d.addCallback(self._done)

        return d

    def _done(self, _):
        self.curr -= 1


class TestCollector(common.TestCase, common.AgencyTestHelper):

    protocol_type = 'Notification'
    protocol_id = 'dummy-notification'

    timeout = 3

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        yield common.AgencyTestHelper.setUp(self)
        desc = yield self.doc_factory(descriptor.Descriptor)
        self.agent = yield self.agency.start_agent(desc)
        self.interest = self.agent.register_interest(DummyCollector)
        self.collector = self.interest.agency_collector.collector
        self.endpoint, self.queue = self.setup_endpoint()

    @defer.inlineCallbacks
    def testRecivingNotification(self):
        self.assertEqual(1, len(self.agent._protocols))
        yield self.recv_notification()
        yield self.wait_agency_for_idle(self.agency, 10)
        self.assertCalled(self.collector, "notified", 1)

    def testRevokingInterest(self):
        self.agent.revoke_interest(DummyCollector)
        self.assertEqual(0, len(self.agent._protocols))

    @defer.inlineCallbacks
    def testNotificationIdle(self):
        self.assertTrue(self.interest.is_idle())
        d = defer.Deferred()
        self.collector.result = d
        yield self.recv_notification()
        self.assertCalled(self.collector, "notified", 1)
        self.assertFalse(self.interest.is_idle())
        d.callback(None)
        self.assertTrue(self.interest.is_idle())


class TestCollectorConcurrency(common.TestCase, common.AgencyTestHelper):

    protocol_type = 'Notification'
    protocol_id = 'dummy-notification'

    timeout = 3

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        yield common.AgencyTestHelper.setUp(self)
        desc = yield self.doc_factory(descriptor.Descriptor)
        self.agent = yield self.agency.start_agent(desc)
        self.interest = self.agent.register_interest(DummyConcurrentCollector)
        self.collector = self.interest.agency_collector.collector
        self.endpoint, self.queue = self.setup_endpoint()

    @common.attr(timescale=0.05)
    @defer.inlineCallbacks
    def testConcurrency(self):
        self.assertTrue(self.interest.is_idle())
        for i in range(10):
            yield self.recv_notification()
        self.assertFalse(self.interest.is_idle())
        self.assertCalled(self.collector, "notified", 5)
        self.assertEqual(self.collector.max, 5)
        self.assertEqual(self.collector.curr, 5)
        self.assertEqual(self.collector.total, 5)
        yield self.wait_agency_for_idle(self.agency, 10)
        self.assertCalled(self.collector, "notified", 10)
        self.assertEqual(self.collector.max, 5)
        self.assertEqual(self.collector.curr, 0)
        self.assertEqual(self.collector.total, 10)
