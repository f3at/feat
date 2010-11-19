# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from twisted.internet import defer
from twisted.trial import unittest
from zope.interface import implements

from feat.common import journal, fiber, serialization
from feat.interface.journal import *
from feat.interface.serialization import *


from . import common
from feat.interface.fiber import TriggerType


class DummyJournalKeeper(object):

    implements(IJournalKeeper)

    def __init__(self):
        self.records = []
        self.registry = []

    ### IJournalKeeper Methods ###

    def register(self, recorder):
        self.registry.append(recorder)

    def record(self, instance_id, entry_id,
               fiber_id, fiber_depth, input, side_effects, output):
        record = (instance_id, entry_id, fiber_id, fiber_depth,
                  ISnapshot(input).snapshot(),
                  ISnapshot(side_effects).snapshot(),
                  ISnapshot(output).snapshot())
        self.records.append(record)


class BasicRecordingDummy(journal.Recorder):

    @journal.recorded()
    def spam(self, accompaniment, extra=None):
        extra = extra and " with " + extra or ""
        return "spam and " + accompaniment + extra

    @journal.recorded("bacon")
    def async_spam(self, accompaniment, extra=None):
        extra = extra and " with " + extra or ""
        result = "spam and " + accompaniment + extra
        f = fiber.Fiber()
        f.addCallback(common.break_chain)
        f.succeed(result)
        return f


class FiberInfoDummy(journal.Recorder):

    def __init__(self, parent, async=False):
        journal.Recorder.__init__(self, parent)
        self.async = async

    def mk_fiber(self, *args):
        f = fiber.Fiber()
        for a in args:
            if self.async:
                f.addCallback(common.break_chain)
            f.addCallback(a)
        return f.succeed()

    @journal.recorded()
    def test(self, _):
        return self.mk_fiber(self.fun1a, self.fun1b)

    @journal.recorded()
    def fun1a(self, _):
        return self.mk_fiber(self.fun2a, self.fun2b)

    @journal.recorded()
    def fun1b(self, _):
        return self.mk_fiber(self.fun2a, self.fun2b)

    @journal.recorded()
    def fun2a(self, _):
        return self.mk_fiber(self.fun3, self.fun3)

    @journal.recorded()
    def fun2b(self, _):
        return self.mk_fiber(self.fun3, self.fun3)

    @journal.recorded()
    def fun3(self, _):
        pass


class NestedRecordedDummy(journal.Recorder):

    @journal.recorded()
    def main(self, a, b):
        return self.funA(a, b) + self.funB(a, b)

    @journal.recorded()
    def funA(self, a, b):
        return self.funC(a, b) + self.funD(a, b)

    @journal.recorded()
    def funB(self, a, b):
        return self.funD(a, b) + self.funD(a, b)

    @journal.recorded()
    def funC(self, a, b):
        return self.funD(a, b) + 7

    @journal.recorded()
    def funD(self, a, b):
        return a + b


class TestJournaling(common.TestCase):

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
        self.assertEqual(A.journal_id, (1, ))
        B = journal.Recorder(R)
        self.assertEqual(B.journal_id, (2, ))
        AA = journal.Recorder(A)
        self.assertEqual(AA.journal_id, (1, 1))

    def testBasicRecording(self):

        def check_records(_, records):
            # Filter out the fiber related fields
            records = [r[:2] + r[4:] for r in records]
            # instance_id should be the same
            iid = records[0][0]

            break_call = (('feat.test.common.break_chain', None, None), None)

            expected = [(iid, "spam", (("beans", ), None),
                         None, "spam and beans"),

                        (iid, "spam", (("beans", ), {"extra": "spam"}),
                         None, "spam and beans with spam"),

                        (iid, "bacon", (("beans", ), None),
                         None, (TriggerType.succeed,
                                "spam and beans",
                                [break_call])),

                        (iid, "bacon", (("beans", ), {"extra": "spam"}),
                         None, (TriggerType.succeed,
                                "spam and beans with spam",
                                [break_call]))]

            self.assertEqual(expected, records)

        keeper = DummyJournalKeeper()
        root = journal.RecorderRoot(keeper)
        obj = BasicRecordingDummy(root)
        self.assertEqual([obj], keeper.registry)
        d = self.assertAsyncEqual(None, "spam and beans",
                                  obj.spam("beans"))
        d = self.assertAsyncEqual(d, "spam and beans with spam",
                                  obj.spam("beans", extra="spam"))
        d = self.assertAsyncEqual(d, "spam and beans",
                                  obj.async_spam("beans"))
        d = self.assertAsyncEqual(d, "spam and beans with spam",
                                  obj.async_spam("beans", extra="spam"))
        return d.addCallback(check_records, keeper.records)

    def testFiberInfo(self):

        def check_fid_and_filter(records):
            fid = records[0][1]
            for record in records:
                self.assertEqual(fid, record[1])
            return fid, [(r[0], r[2]) for r in records]

        def check_records(_, records):
            records = [r[1:4] for r in records]

            # Used to ensure all fibers have different identifier
            fids = set()

            # obj.fun3, only one entry
            entries, records = records[:1], records[1:]
            fid, entries = check_fid_and_filter(entries)
            self.assertFalse(fid in fids)
            fids.add(fid)
            self.assertEqual([("fun3", 0)], entries)

            # obj.fun2a, 3 entries
            entries, records = records[:3], records[3:]
            fid, entries = check_fid_and_filter(entries)
            self.assertFalse(fid in fids)
            fids.add(fid)
            self.assertEqual([("fun2a", 0), ("fun3", 1), ("fun3", 1)], entries)

            # obj.fun1a, 7 entries
            entries, records = records[:7], records[7:]
            fid, entries = check_fid_and_filter(entries)
            self.assertFalse(fid in fids)
            fids.add(fid)
            self.assertEqual([("fun1a", 0),
                              ("fun2a", 1), ("fun3", 2), ("fun3", 2),
                              ("fun2b", 1), ("fun3", 2), ("fun3", 2)], entries)

            # obj.test, 15 entries
            entries, records = records[:15], records[15:]
            fid, entries = check_fid_and_filter(entries)
            self.assertFalse(fid in fids)
            fids.add(fid)
            self.assertEqual([("test", 0),
                              ("fun1a", 1),
                              ("fun2a", 2), ("fun3", 3), ("fun3", 3),
                              ("fun2b", 2), ("fun3", 3), ("fun3", 3),
                              ("fun1b", 1),
                              ("fun2a", 2), ("fun3", 3), ("fun3", 3),
                              ("fun2b", 2), ("fun3", 3), ("fun3", 3)], entries)

        d = defer.succeed(None)

        # Test with "synchronous" fibers where callbacks are called right away
        keeper = DummyJournalKeeper()
        root = journal.RecorderRoot(keeper)
        obj = FiberInfoDummy(root, False)
        d.addCallback(obj.fun3)
        d.addCallback(obj.fun2a)
        d.addCallback(obj.fun1a)
        d.addCallback(obj.test)
        d.addCallback(check_records, keeper.records)

        # test with "real" asynchronous fibers
        keeper = DummyJournalKeeper()
        root = journal.RecorderRoot(keeper)
        obj = FiberInfoDummy(root, True)
        d.addCallback(obj.fun3)
        d.addCallback(obj.fun2a)
        d.addCallback(obj.fun1a)
        d.addCallback(obj.test)
        d.addCallback(check_records, keeper.records)

        return d

    def testNestedRecordedFunction(self):

        def drop_result(_, fun, *args, **kwargs):
            return fun(*args, **kwargs)

        def check_records(_, records):
            self.assertEqual(5, len(records))
            expected = [39, # ((3 + 5) + 7) + (3 + 5)) + ((3 + 5) + (3 + 5))
                        23, # ((3 + 5) + 7) + (3 + 5)
                        16, # (3 + 5) + (3 + 5)
                        15, # (3 + 5) + 7
                         8] # 3 + 5
            self.assertEqual(expected, [r[6] for r in records]),

        keeper = DummyJournalKeeper()
        root = journal.RecorderRoot(keeper)
        obj = NestedRecordedDummy(root)

        d = defer.succeed(None)
        d.addCallback(drop_result, obj.main, 3, 5)
        d.addCallback(drop_result, obj.funA, 3, 5)
        d.addCallback(drop_result, obj.funB, 3, 5)
        d.addCallback(drop_result, obj.funC, 3, 5)
        d.addCallback(drop_result, obj.funD, 3, 5)
        d.addCallback(check_records, keeper.records)

        return d
