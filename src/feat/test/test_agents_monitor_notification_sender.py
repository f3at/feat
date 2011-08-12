from zope.interface import implements

from feat.agents.monitor import monitor_agent
from feat.test import common
from feat.common import defer, time, log, journal, fiber
from feat.agents.base import recipient, descriptor, sender

from feat.agencies.interface import *
from feat.agents.monitor.interface import *
from feat.interface.protocols import *


class DummyBase(journal.DummyRecorderNode, log.LogProxy, log.Logger):

    def __init__(self, logger, now=None):
        journal.DummyRecorderNode.__init__(self)
        log.LogProxy.__init__(self, logger)
        log.Logger.__init__(self, logger)

        self.calls = {}
        self.now = now or time.time()
        self.call = None

    def do_calls(self):
        calls = self.calls.values()
        self.calls.clear()
        for _time, fun, args, kwargs in calls:
            fun(*args, **kwargs)

    def reset(self):
        self.calls.clear()

    def get_time(self):
        return self.now

    def call_later(self, time, fun, *args, **kwargs):
        payload = (time, fun, args, kwargs)
        callid = id(payload)
        self.calls[callid] = payload
        return callid

    def call_later_ex(self, time, fun, args=(), kwargs={}, busy=True):
        payload = (time, fun, args, kwargs)
        callid = id(payload)
        self.calls[callid] = payload
        return callid

    def cancel_delayed_call(self, callid):
        if callid in self.calls:
            del self.calls[callid]


class DummyMedium(DummyBase):
    pass


class DummyAgent(DummyBase):

    def __init__(self, logger):
        DummyBase.__init__(self, logger)
        self.docs = dict()
        self.descriptor = monitor_agent.Descriptor()
        self.protocols = list()

    def reset(self):
        self.protocols = list()
        DummyBase.reset(self)

    def get_descriptor(self):
        return self.descriptor

    def update_descriptor(self, method, *args, **kwargs):
        return fiber.wrap_defer(self._update_descriptor, method,
                                *args, **kwargs)

    def _update_descriptor(self, method, *args, **kwargs):
        return defer.succeed(method(self.descriptor, *args, **kwargs))

    def get_document(self, doc_id):
        if doc_id in self.docs:
            return fiber.succeed(self.docs[doc_id])
        else:
            return fiber.fail(NotFoundError())

    def initiate_protocol(self, factory, *args, **kwargs):
        instance = DummyProtocol(factory, args, kwargs)
        self.protocols.append(instance)
        return instance


class DummyProtocol(object):

    def __init__(self, factory, args, kwargs):
        self.factory = factory
        self.args = args
        self.kwargs = kwargs
        self.deferred = defer.Deferred()

    def notify_finish(self):
        return fiber.wrap_defer(self.get_def)

    def get_def(self):
        return self.deferred


class DummyClerk(dict):
    implements(IClerk)

    def has_patient(self, agent_id):
        return agent_id in self

    def get_patient(self, agent_id):
        status = self.get(agent_id, None)
        if status is not None:
            return Status(status)


class Status(object):
    implements(IPatientStatus)

    def __init__(self, status):
        self.state = status


class NotificationSenderTest(common.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        self.medium = DummyMedium(self)
        self.agent = DummyAgent(self)
        self.clerk = DummyClerk()
        self.task = sender.NotificationSender(self.agent, self.medium)
        yield self.task.initiate(self.clerk)
        self.recp = recipient.Agent(agent_id='agent_id', route='shard')

    @defer.inlineCallbacks
    def testDryRunMethod(self):
        # dry run should not trigger anything
        yield self.task.run()
        self.assert_protocols(0)

    @defer.inlineCallbacks
    def testNonExistingAgnet(self):
        # check sending notification to nonexisting agent (no descriptor)
        n1 = self.gen_notification(recipient=self.recp)
        notification = self.gen_notification(recipient=self.recp)
        yield self.task.notify([n1, notification])
        self.assert_pending('agent_id', 2)

        d = self.task.run()
        self.assert_protocols(1)
        self.fail_protocol(0)
        yield d
        self.assert_pending('agent_id', 0)

    @defer.inlineCallbacks
    def testExistingAgent(self):
        # now tests same thing, but with descriptor existing
        self.agent.reset()
        notification = self.gen_notification(recipient=self.recp)
        self.gen_document(self.recp)

        yield self.task.notify([notification])
        self.assert_pending('agent_id', 1)
        d = self.task.run()
        self.assert_protocols(1)
        self.fail_protocol(0)
        yield d
        self.assert_pending('agent_id', 1)

    @defer.inlineCallbacks
    def testSuccessfulFlushing(self):
        n1 = self.gen_notification(recipient=self.recp)
        n2 = self.gen_notification(recipient=self.recp)
        self.task.notify([n1, n2])
        d = self.task.run()
        self.assert_pending('agent_id', 2)
        self.assert_protocols(1)
        self.succeed_protocol(0)
        self.assert_pending('agent_id', 1)
        self.assert_protocols(2)
        self.succeed_protocol(1)
        yield d
        self.assert_pending('agent_id', 0)

    @defer.inlineCallbacks
    def testIntegrationWithClerk(self):
        self.clerk['agent_id'] = PatientState.dead
        n1 = self.gen_notification(recipient=self.recp)
        n2 = self.gen_notification(recipient=self.recp)
        self.task.notify([n1, n2])
        d = self.task.run()
        self.assert_pending('agent_id', 2)
        self.assert_protocols(0)
        yield d

        self.clerk['agent_id'] = PatientState.alive
        d = self.task.run()
        self.assert_pending('agent_id', 2)
        self.assert_protocols(1)
        self.fail_protocol(0)
        yield d
        self.assert_pending('agent_id', 0)

    @defer.inlineCallbacks
    def testMigratingShard(self):
        n1 = self.gen_notification(recipient=self.recp)
        n2 = self.gen_notification(recipient=self.recp)
        self.task.notify([n1, n2])

        new_recp = recipient.Agent(self.recp.key, route=u'other shard')
        self.gen_document(new_recp)

        d = self.task.run()
        self.assert_pending('agent_id', 2)
        self.assert_protocols(1)
        self.fail_protocol(0)
        yield d

        self.assert_pending('agent_id', 2)
        for notif in self.agent.descriptor.pending_notifications['agent_id']:
            self.assertEqual('other shard', notif.recipient.route)

    def assert_pending(self, agent_id, num):
        if num == 0:
            self.assertFalse(agent_id in
                             self.agent.descriptor.pending_notifications)
        else:
            self.assertTrue(agent_id in
                            self.agent.descriptor.pending_notifications)
            self.assertEqual(
                num,
                len(self.agent.descriptor.pending_notifications[agent_id]))

    def gen_document(self, recp):
        self.agent.docs[recp.key] = descriptor.Descriptor(doc_id=recp.key,
                                                          shard=recp.route)

    def succeed_protocol(self, index):
        self.agent.protocols[index].deferred.callback(None)

    def fail_protocol(self, index):
        self.agent.protocols[index].deferred.errback(ProtocolFailed())

    def assert_protocols(self, num):
        self.assertEqual(num, len(self.agent.protocols))

    def gen_notification(self, **options):
        return sender.PendingNotification(**options)
