from zope.interface import implements

from feat.agents.base import message
from feat.agents.monitor import production
from feat.common import journal, log, time

from feat.agents.monitor.interface import *

from feat.test import common
from feat.agencies import periodic


class DummyPatron(journal.DummyRecorderNode, log.LogProxy):

    implements(IDoctor)

    def __init__(self, logger, now=None):
        journal.DummyRecorderNode.__init__(self)
        log.LogProxy.__init__(self, logger)
        self.protocol = None
        self.calls = {}
        self.death = []
        self.now = now or time.time()
        self.call = None

    ### Public Methods ###

    def do_calls(self):
        calls = self.calls.values()
        self.calls.clear()
        for _time, fun, args, kwargs in calls:
            fun(*args, **kwargs)

    def initiate_protocol(self, factory, *args, **kwargs):
        if isinstance(factory, periodic.PeriodicProtocolFactory):
            if factory.factory is production.CheckPatientTask:
                self._start_task(factory.period, factory.factory, args, kwargs)
                return self
        raise Exception("Unexpected protocol")

    def cancel(self):
        if self.call:
            self.cancel_delayed_call(self.call)

    ### IDoctor Methods ###

    def register_interest(self, factory, *args, **kwargs):
        assert self.protocol is None
        self.protocol = factory(self, self)
        self.protocol.initiate(*args, **kwargs)

    def get_time(self):
        return self.now

    def call_later(self, time, fun, *args, **kwargs):
        payload = (time, fun, args, kwargs)
        callid = id(payload)
        self.calls[callid] = payload
        return callid

    def cancel_delayed_call(self, callid):
        if callid in self.calls:
            del self.calls[callid]

    def on_heart_failed(self, agent_id, instance_id, payload):
        self.death.append((agent_id, instance_id))

    def _start_task(self, period, factory, args, kwargs):
        task = factory(self, self)
        task.initiate(*args, **kwargs)
        self.call = self.call_later(period, self._start_task,
                                    period, factory, args, kwargs)


class TestMonitorProductionLabour(common.TestCase):

    def testPatient(self):
        now = time.time()

        patient = production.Patient(None, None, None, now, 5, 3)
        self.assertEqual((PatientState.alive, PatientState.alive),
                         patient.check(now))
        self.assertEqual((PatientState.alive, PatientState.alive),
                         patient.check(now + 4))
        self.assertEqual((PatientState.alive, PatientState.alive),
                         patient.check(now + 6))
        self.assertEqual((PatientState.alive, PatientState.dying),
                         patient.check(now + 14))
        self.assertEqual((PatientState.dying, PatientState.dead),
                         patient.check(now + 16))

        patient = production.Patient(None, None, None, now, 5, 3)
        self.assertEqual((PatientState.alive, PatientState.alive),
                         patient.check(now))
        patient.beat(now + 5)
        self.assertEqual((PatientState.alive, PatientState.alive),
                         patient.check(now + 6))
        self.assertEqual((PatientState.alive, PatientState.dying),
                         patient.check(now + 13))
        patient.beat(now + 12)
        self.assertEqual((PatientState.dying, PatientState.alive),
                         patient.check(now + 15))
        self.assertEqual((PatientState.alive, PatientState.alive),
                         patient.check(now + 18))
        self.assertEqual((PatientState.alive, PatientState.dying),
                         patient.check(now + 23))
        self.assertEqual((PatientState.dying, PatientState.dying),
                         patient.check(now + 23))
        patient.beat(now + 26)
        self.assertEqual((PatientState.dying, PatientState.alive),
                         patient.check(now + 27))

    def testHartMonitor(self):
        patron = DummyPatron(self)
        monitor = production.HeartMonitor(patron, 2)
        monitor.startup()
        self.assertTrue(isinstance(patron.protocol,
                                   production.HeartBeatCollector))
        self.assertEqual(len(patron.calls), 1)
        self.assertEqual(patron.death, [])

        monitor.add_patient("aid1", "iid1", period=5, max_skip=3)
        monitor.add_patient("aid2", "iid2", period=5, max_skip=3)

        # 6 seconds without heart-beats
        patron.now += 3
        patron.do_calls()
        self.assertEqual(len(patron.calls), 1)
        self.assertEqual(patron.death, [])

        patron.now += 3
        patron.do_calls()
        self.assertEqual(len(patron.calls), 1)
        self.assertEqual(patron.death, [])

        # Both send heart-beat
        hb1 = message.Notification(payload=("aid1", "iid1"))
        patron.protocol.notified(hb1)
        hb2 = message.Notification(payload=("aid2", "iid2"))
        patron.protocol.notified(hb2)
        self.assertEqual(patron.death, [])
        patron.do_calls()
        self.assertEqual(patron.death, [])

        # Both skip 2 heart beats
        patron.now += 11
        patron.do_calls()
        self.assertEqual(patron.death, [])

        # Only one send heart-beat
        hb1 = message.Notification(payload=("aid1", "iid1"))
        patron.protocol.notified(hb1)

        # One died
        patron.now += 5
        patron.do_calls()
        self.assertEqual(patron.death, [("aid2", "iid2")])

        # Send heart beat for a dead agent
        patron.now += 5
        hb2 = message.Notification(payload=("aid2", "iid2"))
        patron.protocol.notified(hb2)
        patron.do_calls()
        self.assertEqual(patron.death, [("aid2", "iid2")])

        # Remove patient, and stop heart-beats
        monitor.remove_patient("aid1", "iid1")
        patron.now += 10
        patron.do_calls()
        self.assertEqual(patron.death, [("aid2", "iid2")])

        monitor.cleanup()
        self.assertEqual(len(patron.calls), 0)
