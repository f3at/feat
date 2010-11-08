# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from zope.interface import implements

from feat.common import journal
from feat.interface import journaling

from . import common


class DummyJournalKeeper(object):

    implements(journaling.IJournalKeeper)

    records = []

    ### IJournalKeeper Methods ###

    def record(self, instance_id, entry_id, input, output):
        record = ( instance_id, entry_id, input.snapshot(), output.snapshot())
        self.records.append(record)


class A(journal.Recorder):

    @journal.recorded()
    def spam(self, accompaniment):
        pass

    @journal.recorded("bacon")
    def more_spam(self, accompaniment):
        pass


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

    def testRecording(self):
        pass