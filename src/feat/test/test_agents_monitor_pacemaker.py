from zope.interface import implements

from feat.agents.base import message
from feat.agents.monitor import pacemaker
from feat.common import journal, log

from feat.agents.monitor.interface import *
from feat.interface.agent import *

from feat.test import common


class DummyDescriptor(object):

    def __init__(self, aid, iid):
        self.doc_id = aid
        self.instance_id = iid


class DummyPatron(journal.DummyRecorderNode, log.LogProxy):

    implements(IAgent)

    def __init__(self, logger, descriptor):
        journal.DummyRecorderNode.__init__(self)
        log.LogProxy.__init__(self, logger)

        self.descriptor = descriptor
        self.calls = {}

        self.messages = []
        self.protocol = None
        self.task = None

    ### Public Methods ###

    def do_calls(self):
        calls = self.calls.values()
        self.calls.clear()
        for _time, fun, args, kwargs in calls:
            fun(*args, **kwargs)

    ### IAgent Methods ###

    def initiate_protocol(self, factory, recipient, *args, **kwargs):
        assert self.protocol is None
        self.protocol = factory(self, self)
        self.protocol.initiate(*args, **kwargs)
        return self.protocol

    def initiate_task(self, factory, *args, **kwargs):
        assert self.task is None
        self.task = factory(self, self)
        self.task.initiate(*args, **kwargs)
        return self.task

    def get_full_id(self):
        return "%s/%s" % (self.descriptor.doc_id, self.descriptor.instance_id)

    def get_descriptor(self):
        return self.descriptor

    def get_time(self):
        raise NotImplementedError()

    def call_later(self, time, fun, *args, **kwargs):
        payload = (time, fun, args, kwargs)
        callid = id(payload)
        self.calls[callid] = payload
        return callid

    def cancel_delayed_call(self, callid):
        if callid in self.calls:
            del self.calls[callid]

    ### Mediums Methods ###

    def finish(self, task):
        assert task is self.task
        self.task = None

    def post(self, msg):
        self.messages.append(msg)


class TestPacemaker(common.TestCase):

    def testPacemaker(self):
        descriptor = DummyDescriptor("aid", "iid")
        patron = DummyPatron(self, descriptor)
        labour = pacemaker.Pacemaker(patron, "monitor", 3)
        labour.initiate()

        self.assertTrue(isinstance(patron.protocol, pacemaker.HeartBeatPoster))
        self.assertTrue(isinstance(patron.task, pacemaker.HeartBeatTask))
        self.assertEqual(len(patron.messages), 1)
        msg = patron.messages.pop()
        self.assertEqual(msg.payload, ("aid", "iid", 0))
        self.assertEqual(len(patron.calls), 1)
        call = patron.calls.itervalues().next()
        self.assertEqual(call[0], 3)

        patron.do_calls()

        self.assertEqual(len(patron.messages), 1)
        msg = patron.messages.pop()
        self.assertEqual(msg.payload, ("aid", "iid", 1))
        self.assertEqual(len(patron.calls), 1)

        labour.cleanup()
        self.assertEqual(patron.task, None)
        self.assertEqual(len(patron.calls), 0)

        # Double cleanup should work
        labour.cleanup()
        self.assertEqual(patron.task, None)
        self.assertEqual(len(patron.calls), 0)
