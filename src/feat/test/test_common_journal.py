# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from twisted.internet import defer
from zope.interface import implements

from feat.common import journal, fiber
from feat.interface import journaling, async

from . import common


class DummyJournalKeeper(object):

    implements(journaling.IJournalKeeper)

    def __init__(self):
        self.records = []

    ### IJournalKeeper Methods ###

    def register(self, recorder):
        pass

    def record(self, instance_id, entry_id, input, output):
        record = (instance_id, entry_id, input.snapshot(), output.snapshot())
        self.records.append(record)


class DummyFiber(object):

    implements(async.IFiber)

    def __init__(self, value):
        self.value = value
        self.started = False

    ### serialization.ISnapshot ###

    def snapshot(self, context={}):
        return self.value

    ### async.IFiber ###

    def run(self):
        self.started = True


class A(journal.Recorder):

    @journal.recorded()
    def spam(self, accompaniment):
        return "spam and " + accompaniment

    @journal.recorded("bacon")
    def async_spam(self, accompaniment):
        return DummyFiber("spam and " + accompaniment)


class TestRecorder(common.TestCase):

    def testJournalId(self):
        K = DummyJournalKeeper()
        R = journal.RecorderRoot(K, base_id="test")
        A = journal.Recorder(R)
        self.assertEqual(A.journal_id, ("test", 1))
        B = journal.Recorder(R)
        self.assertEqual(B.journal_id, ("test", 2))
        AA = journal.Recorder(A)
        self.assertEqual(AA.journal_id, ("test", 1, 1))
        AB = journal.Recorder(A)
        self.assertEqual(AB.journal_id, ("test", 1, 2))
        ABA = journal.Recorder(AB)
        self.assertEqual(ABA.journal_id, ("test", 1, 2, 1))
        BA = journal.Recorder(B)
        self.assertEqual(BA.journal_id, ("test", 2, 1))

        R = journal.RecorderRoot(K)
        A = journal.Recorder(R)
        self.assertEqual(A.journal_id, (1,))
        B = journal.Recorder(R)
        self.assertEqual(B.journal_id, (2,))
        AA = journal.Recorder(A)
        self.assertEqual(AA.journal_id, (1, 1))

    def testAdaptation(self):
        recres = journaling.IRecordingResult(fiber.Fiber())
        self.assertTrue(isinstance(recres, journal.RecordingAsyncResult))
        recres = journaling.IRecordingResult(1)
        self.assertTrue(isinstance(recres, journal.RecordingSyncResult))
        recres = journaling.IRecordingResult([])
        self.assertTrue(isinstance(recres, journal.RecordingSyncResult))
        recres = journaling.IRecordingResult((1, 2))
        recres = journaling.IRecordingResult({})
        self.assertTrue(isinstance(recres, journal.RecordingSyncResult))
        self.assertTrue(isinstance(recres, journal.RecordingSyncResult))
        recres = journaling.IRecordingResult(None)
        self.assertTrue(isinstance(recres, journal.RecordingSyncResult))
        recres = journaling.IRecordingResult("test")
        self.assertTrue(isinstance(recres, journal.RecordingSyncResult))
        try:
            journaling.IRecordingResult(defer.succeed(None))
            self.fail("Twisted Deferred is not a valid result for recorded functions")
        except journal.RecordResultError:
            # Expected
            pass

    def testRecording(self):
        k = DummyJournalKeeper()
        r = journal.RecorderRoot(k)
        o = A(r)
        self.assertEqual("spam and beans", o.spam("beans"))
