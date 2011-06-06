from zope.interface import implements

from feat.agencies import periodic
from feat.agents.base import message
from feat.agents.monitor import pacemaker
from feat.common import journal, log, defer

from feat.agents.monitor.interface import *
from feat.interface.agent import *
from feat.interface.task import *

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
        self.cid = 0

        self.messages = []

        self.poster = None

    ### Public Methods ###

    def do_calls(self):
        calls = self.calls.values()
        self.calls.clear()
        for _time, fun, args, kwargs in calls:
            fun(*args, **kwargs)

    ### IAgent Methods ###

    def initiate_protocol(self, factory, *args, **kwargs):
        if factory is pacemaker.HeartBeatPoster:
            self.poster = pacemaker.HeartBeatPoster(self, self)
            # Remove recipient
            args = args[1:]
            self.poster.initiate(*args, **kwargs)
            return self.poster

        if factory is pacemaker.HeartBeatTask:
            self.task = pacemaker.HeartBeatTask(self, self)
            self.task.initiate(*args, **kwargs)
            return self.task

        raise Exception("Unexpected protocol %r" % factory)

    def periodic_protocol(self, factory, period, *args, **kwargs):
        raise Exception("Unexpected protocol")

    def get_full_id(self):
        return "%s/%s" % (self.descriptor.doc_id, self.descriptor.instance_id)

    def get_descriptor(self):
        return self.descriptor

    def _terminate(self, result):
        pass

    ### Mediums Methods ###

    def call_next(self, fun, *args, **kwargs):
        self.cid += 1
        self.calls[self.cid] = (0, fun, args, kwargs)
        return self.cid

    def call_later_ex(self, time, fun, args=(), kwargs={}, busy=True):
        self.cid += 1
        self.calls[self.cid] = (time, fun, args, kwargs)
        return self.cid

    def cancel_delayed_call(self, dc):
        if dc in self.calls:
            del self.calls[dc]

    def post(self, msg):
        self.messages.append(msg)


class TestPacemaker(common.TestCase):

    def testPacemaker(self):
        descriptor = DummyDescriptor("aid", "iid")
        patron = DummyPatron(self, descriptor)
        labour = pacemaker.Pacemaker(patron, "monitor", 3)
        labour.startup()

        self.assertEqual(len(patron.messages), 1)
        msg = patron.messages.pop()
        self.assertEqual(msg.payload, ("aid", "iid"))
        call = patron.calls.itervalues().next()
        self.assertEqual(call[0], 3)

        patron.do_calls()

        self.assertEqual(len(patron.messages), 1)
        msg = patron.messages.pop()
        self.assertEqual(msg.payload, ("aid", "iid"))
        self.assertEqual(len(patron.calls), 1)

        labour.cleanup()
