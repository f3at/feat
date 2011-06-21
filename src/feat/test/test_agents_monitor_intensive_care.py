from zope.interface import implements

from feat.agents.base import message, recipient
from feat.agents.monitor import intensive_care
from feat.common import journal, log, time

from feat.agents.monitor.interface import *

from feat.test import common


class DummyPatron(journal.DummyRecorderNode, log.LogProxy):

    implements(IDoctor, IAssistant)

    def __init__(self, logger, now=None):
        journal.DummyRecorderNode.__init__(self)
        log.LogProxy.__init__(self, logger)
        self.protocol = None
        self.calls = {}
        self.now = now or time.time()
        self.call = None

        self.reset()


    ### Public Methods ###

    def do_calls(self):
        calls = self.calls.values()
        self.calls.clear()
        for _time, fun, args, kwargs in calls:
            fun(*args, **kwargs)

    def cancel(self):
        if self.call:
            self.cancel_delayed_call(self.call)

    def terminate(self):
        pass

    def reset(self):
        self.deads = []
        self.dyings = []
        self.resurecteds = []

    ### IAssistant ###

    def initiate_protocol(self, factory, *args, **kwargs):
        if factory is intensive_care.HeartBeatCollector:
            self.protocol = intensive_care.HeartBeatCollector(self, self)
            # Remove recipient
            args = args[1:]
            self.protocol.initiate(*args, **kwargs)
            return self.protocol

        if factory is intensive_care.CheckPatientTask:
            self.task = intensive_care.CheckPatientTask(self, self)
            self.task.initiate(*args, **kwargs)
            return self.task

        raise Exception("Unexpected protocol %r" % factory)

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

    def call_later_ex(self, time, fun, args=(), kwargs={}, busy=True):
        payload = (time, fun, args, kwargs)
        callid = id(payload)
        self.calls[callid] = payload
        return callid

    def cancel_delayed_call(self, callid):
        if callid in self.calls:
            del self.calls[callid]

    ### IDoctor ###

    def on_patient_added(self, patient):
        pass

    def on_patient_removed(self, patient):
        pass

    def on_patient_dying(self, patient):
        self.dyings.append(patient.recipient)

    def on_patient_died(self, patient):
        self.deads.append(patient.recipient)

    def on_patient_resurrected(self, patient):
        self.resurecteds.append(patient.recipient)

    ### private ###

    def _start_task(self, period, factory, args, kwargs):
        task = factory(self, self)
        task.initiate(*args, **kwargs)
        self.call = self.call_later(period, self._start_task,
                                    period, factory, args, kwargs)


class TestIntensiveCare(common.TestCase):

    def testPatient(self):
        now = time.time()

        patient = intensive_care.Patient(None, None, now, 5, 1.5, 3)
        self.assertEqual((PatientState.alive, PatientState.alive),
                         patient.check(now))
        self.assertEqual((PatientState.alive, PatientState.alive),
                         patient.check(now + 4))
        self.assertEqual((PatientState.alive, PatientState.alive),
                         patient.check(now + 6))
        self.assertEqual((PatientState.alive, PatientState.dying),
                         patient.check(now + 8))
        self.assertEqual((PatientState.dying, PatientState.dying),
                         patient.check(now + 11))
        self.assertEqual((PatientState.dying, PatientState.dead),
                         patient.check(now + 16))

        patient = intensive_care.Patient(None, None, now, 5, 1.5, 3)
        self.assertEqual((PatientState.alive, PatientState.alive),
                         patient.check(now))

        now += 5
        patient.beat(now)

        self.assertEqual((PatientState.alive, PatientState.alive),
                         patient.check(now + 1))
        self.assertEqual((PatientState.alive, PatientState.dying),
                         patient.check(now + 8))

        now += 7
        patient.beat(now)

        self.assertEqual((PatientState.dying, PatientState.alive),
                         patient.check(now))
        self.assertEqual((PatientState.alive, PatientState.alive),
                         patient.check(now + 6))
        self.assertEqual((PatientState.alive, PatientState.dying),
                         patient.check(now + 8))
        self.assertEqual((PatientState.dying, PatientState.dying),
                         patient.check(now + 11))

        now += 11
        patient.beat(now)

        self.assertEqual((PatientState.dying, PatientState.alive),
                          patient.check(now))
        self.assertEqual((PatientState.alive, PatientState.alive),
                         patient.check(now + 6))
        self.assertEqual((PatientState.alive, PatientState.dying),
                         patient.check(now + 8))
        self.assertEqual((PatientState.dying, PatientState.dead),
                         patient.check(now + 16))
        self.assertEqual((PatientState.dead, PatientState.dead),
                         patient.check(now + 80))

        now += 80
        patient.beat(now)

        self.assertEqual((PatientState.dead, PatientState.alive),
                         patient.check(now))

    def testIntensiveCare(self):
        patron = DummyPatron(self)
        monitor = intensive_care.IntensiveCare(patron, patron, 2)
        monitor.startup()
        self.assertTrue(isinstance(patron.protocol,
                                   intensive_care.HeartBeatCollector))
        self.assertEqual(len(patron.calls), 1)
        self.assertEqual(patron.deads, [])
        self.assertEqual(patron.dyings, [])
        self.assertEqual(patron.resurecteds, [])

        recip1 = recipient.Recipient("agent1", "shard1")
        recip2 = recipient.Recipient("agent2", "shard1")

        monitor.add_patient(recip1, None, period=5,
                            dying_skips=1.5, death_skips=3)
        monitor.add_patient(recip2, None, period=5,
                            dying_skips=1.5, death_skips=3)

        # 6 seconds without heart-beats
        patron.now += 3
        patron.do_calls()

        self.assertEqual(len(patron.calls), 1)
        self.assertEqual(patron.deads, [])
        self.assertEqual(patron.dyings, [])
        self.assertEqual(patron.resurecteds, [])

        patron.now += 3
        patron.do_calls()

        self.assertEqual(len(patron.calls), 1)
        self.assertEqual(patron.deads, [])
        self.assertEqual(patron.dyings, [])
        self.assertEqual(patron.resurecteds, [])

        # Both send heart-beat
        hb1 = message.Notification(payload=("agent1", 0, 0))
        patron.protocol.notified(hb1)
        hb2 = message.Notification(payload=("agent2", 0, 0))
        patron.protocol.notified(hb2)

        self.assertEqual(patron.deads, [])
        self.assertEqual(patron.dyings, [])
        self.assertEqual(patron.resurecteds, [])

        patron.do_calls()

        self.assertEqual(patron.deads, [])
        self.assertEqual(patron.dyings, [])
        self.assertEqual(patron.resurecteds, [])

        # Both skip 1.5 heart beats
        patron.now += 8
        patron.do_calls()

        self.assertEqual(patron.deads, [])
        self.assertEqual(len(patron.dyings), 2)
        self.assertEqual(patron.resurecteds, [])
        self.assertTrue(recip1 in patron.dyings)
        self.assertTrue(recip2 in patron.dyings)

        patron.reset()

        # Only one send heart-beat
        hb1 = message.Notification(payload=("agent1", 0, 1))
        patron.protocol.notified(hb1)

        patron.now += 6
        patron.do_calls()

        self.assertEqual(patron.deads, [])
        self.assertEqual(patron.dyings, [])
        self.assertEqual(len(patron.resurecteds), 1)
        self.assertTrue(recip1 in patron.resurecteds)

        patron.reset()

        # One died
        patron.now += 8
        patron.do_calls()

        self.assertEqual(len(patron.deads), 1)
        self.assertEqual(len(patron.dyings), 1)
        self.assertEqual(len(patron.resurecteds), 0)
        self.assertTrue(recip1 in patron.dyings)
        self.assertTrue(recip2 in patron.deads)

        patron.reset()

        # a few normal heart beats
        hb1 = message.Notification(payload=("agent1", 0, 2))
        patron.protocol.notified(hb1)

        patron.now += 5
        patron.do_calls()

        self.assertEqual(len(patron.deads), 0)
        self.assertEqual(len(patron.dyings), 0)
        self.assertEqual(len(patron.resurecteds), 1)
        self.assertTrue(recip1 in patron.resurecteds)

        patron.reset()

        # a few normal heart beats
        hb1 = message.Notification(payload=("agent1", 0, 3))
        patron.protocol.notified(hb1)

        patron.now += 5
        patron.do_calls()

        self.assertEqual(len(patron.deads), 0)
        self.assertEqual(len(patron.dyings), 0)
        self.assertEqual(len(patron.resurecteds), 0)

        # a few normal heart beats
        hb1 = message.Notification(payload=("agent1", 0, 4))
        patron.protocol.notified(hb1)

        patron.now += 5
        patron.do_calls()

        self.assertEqual(len(patron.deads), 0)
        self.assertEqual(len(patron.dyings), 0)
        self.assertEqual(len(patron.resurecteds), 0)

        # Then resurect the dead
        hb1 = message.Notification(payload=("agent1", 0, 5))
        patron.protocol.notified(hb1)
        hb2 = message.Notification(payload=("agent2", 0, 1))
        patron.protocol.notified(hb2)

        patron.now += 5
        patron.do_calls()

        self.assertEqual(len(patron.deads), 0)
        self.assertEqual(len(patron.dyings), 0)
        self.assertEqual(len(patron.resurecteds), 1)
        self.assertTrue(recip2 in patron.resurecteds)

        patron.reset()

        # Send heart beat for an unknown agent

        hb3 = message.Notification(payload=("agent3", 0, 0))
        patron.protocol.notified(hb3)

        patron.now += 2
        patron.do_calls()

        self.assertEqual(len(patron.deads), 0)
        self.assertEqual(len(patron.dyings), 0)
        self.assertEqual(len(patron.resurecteds), 0)

        # Remove patient, and stop heart-beats
        monitor.remove_patient(recip1)

        patron.now += 2
        patron.do_calls()

        self.assertEqual(len(patron.deads), 0)
        self.assertEqual(len(patron.dyings), 1)
        self.assertEqual(len(patron.resurecteds), 0)
        self.assertTrue(recip2 in patron.dyings)

        patron.reset()

        patron.now += 7
        patron.do_calls()

        self.assertEqual(len(patron.deads), 1)
        self.assertEqual(len(patron.dyings), 0)
        self.assertEqual(len(patron.resurecteds), 0)
        self.assertTrue(recip2 in patron.deads)

        monitor.cleanup()
        self.assertEqual(len(patron.calls), 0)
