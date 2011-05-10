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

        self.messages = []

        self.poster = None
        self.canceled = False

    ### Public Methods ###

    def start_task(self):
        assert self.poster is not None
        task = pacemaker.HeartBeatTask(self, self)
        return task.initiate(self.poster)

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

        if isinstance(factory, periodic.PeriodicProtocolFactory):
            if factory.factory is pacemaker.HeartBeatTask:
                return self

        raise Exception("Unexpected protocol")

    def periodic_protocol(self, factory, period, *args, **kwargs):
        raise Exception("Unexpected protocol")

    def get_full_id(self):
        return "%s/%s" % (self.descriptor.doc_id, self.descriptor.instance_id)

    def get_descriptor(self):
        return self.descriptor

    def _terminate(self, result):
        pass

    ### Mediums Methods ###

    def cancel(self):
        self.canceled = True

    def post(self, msg):
        self.messages.append(msg)


class TestPacemaker(common.TestCase):

    @defer.inlineCallbacks
    def testPacemaker(self):
        descriptor = DummyDescriptor("aid", "iid")
        patron = DummyPatron(self, descriptor)
        labour = pacemaker.Pacemaker(patron, "monitor", 3)
        labour.startup()

        yield patron.start_task()

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

        self.assertFalse(patron.canceled)
        labour.cleanup()
        self.assertTrue(patron.canceled)

        # Double cleanup should work
        labour.cleanup()
        self.assertTrue(patron.canceled)
