#-*- coding: utf-8 -*-
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
        self.registry = {}

    ### IJournalKeeper Methods ###

    def register(self, recorder):
        self.registry[recorder.journal_id] = recorder

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


class DirectReplayDummy(journal.Recorder):

    def __init__(self, parent):
        journal.Recorder.__init__(self, parent)
        self.foo = 0
        self.bar = 0
        self.baz = 0

    @journal.recorded()
    def foo(self, value):
        self.foo += value
        return self.foo

    @journal.recorded()
    def bar(self, value, minus=0):
        self.bar += value - minus
        return self.bar

    @journal.recorded()
    def barr(self, minus=0):
        self.bar -= minus
        return self.bar

    @journal.recorded()
    def baz(self, value):

        def async_add(v):
            self.baz += v
            return self.baz

        f = fiber.Fiber()
        f.addCallback(async_add)
        f.succeed(value)
        return f


class RecordReplayDummy(journal.Recorder):

    def __init__(self, parent):
        journal.Recorder.__init__(self, parent)
        self.reset()

    def reset(self):
        self.servings = []

    def snapshot(self, context={}):
        return self.servings

    @journal.recorded()
    def spam(self, accompaniment, extra=None):
        extra = extra and " with " + extra or ""
        serving = "spam and %s%s" % (accompaniment, extra)
        return self._addServing(serving)

    @journal.recorded()
    def double_bacon(self, accompaniment):
        serving = "bacon and %s" % accompaniment
        self._addServing(serving)
        f = fiber.Fiber()
        f.addCallback(self.spam, extra=accompaniment)
        f.addCallback(self._prepare_double, serving)
        f.succeed("bacon")
        return f

    @journal.recorded()
    def _addServing(self, serving):
        '''Normally called only by other recorded functions'''
        self.servings.append(serving)
        return serving

    def _prepare_double(self, second_serving, first_serving):
        '''Should not modify state, because it's not journalled'''
        return first_serving + " followed by " + second_serving


class ReentrantDummy(journal.Recorder):

    @journal.recorded()
    def good(self):
        return "the good, " + self.bad()

    @journal.recorded()
    def bad(self):
        return "the bad and " + self.ugly()

    @journal.recorded(reentrant=False)
    def ugly(self):
        return "the ugly"


class ErrorDummy(journal.Recorder):

    @journal.recorded()
    def foo(self):
        return "foo"

    @journal.recorded()
    def bar(self):
        return "bar"

    @journal.recorded("baz")
    def barr(self):
        return "barr"

    @journal.recorded()
    def bad(self):
        return defer.succeed(None)

    @journal.recorded()
    def super_bad(self):
        return self.bad()


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
        self.assertTrue(obj.journal_id in keeper.registry)
        self.assertTrue(obj in keeper.registry.values())
        d = self.assertAsyncEqual(None, "spam and beans",
                                  obj.spam, "beans")
        d = self.assertAsyncEqual(d, "spam and beans with spam",
                                  obj.spam, "beans", extra="spam")
        d = self.assertAsyncEqual(d, "spam and beans",
                                  obj.async_spam, "beans")
        d = self.assertAsyncEqual(d, "spam and beans with spam",
                                  obj.async_spam, "beans", extra="spam")
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

    def testDirectReplay(self):

        def snapshot(result):
            side_effects, output = result
            return (ISnapshot(side_effects).snapshot(),
                    ISnapshot(output).snapshot())

        k = DummyJournalKeeper()
        r = journal.RecorderRoot(k)
        o = DirectReplayDummy(r)
        self.assertEqual(o.foo, 0)
        self.assertEqual(o.bar, 0)
        self.assertEqual(o.baz, 0)

        self.assertEqual((None, 3), o.replay("foo", ((3, ), {})))
        self.assertEqual(3, o.foo)
        self.assertEqual((None, 6), o.replay("foo", ((3, ), None)))
        self.assertEqual(6, o.foo)

        self.assertEqual((None, 2), o.replay("bar", ((2, ), {})))
        self.assertEqual(2, o.bar)
        self.assertEqual((None, 4), o.replay("bar", ((2, ), None)))
        self.assertEqual(4, o.bar)
        self.assertEqual((None, 5), o.replay("bar", ((2, ), {"minus": 1})))
        self.assertEqual(5, o.bar)
        self.assertEqual((None, 3), o.replay("barr", ((), {"minus": 2})))
        self.assertEqual(3, o.bar)
        self.assertEqual((None, 2), o.replay("barr", (None, {"minus": 1})))
        self.assertEqual(2, o.bar)

        # Test that fibers are not executed
        self.assertEqual((None, (TriggerType.succeed, 5,
                                 [(("feat.test.test_common_journal.async_add",
                                    None, None),
                                   None)])),
                         snapshot(o.replay("baz", ((5, ), None))))
        self.assertEqual(0, o.baz)
        self.assertEqual((None, (TriggerType.succeed, 8,
                                 [(("feat.test.test_common_journal.async_add",
                                    None, None),
                                   None)])),
                         snapshot(o.replay("baz", ((8, ), None))))
        self.assertEqual(0, o.baz)

    def testRecordReplay(self):

        def replay(_, keeper):
            # Keep objects states and reset before replaying
            states = {}
            for jid, obj in keeper.registry.iteritems():
                states[jid] = obj.snapshot()
                obj.reset()

            # Replaying
            for record in keeper.records:
                jid, fid, _, _, input, exp_side_effects, exp_output = record
                self.assertTrue(jid in keeper.registry)
                obj = keeper.registry[jid]
                side_effects, output = obj.replay(fid, input)
                self.assertEqual(exp_side_effects,
                                 ISnapshot(side_effects).snapshot())
                self.assertEqual(exp_output,
                                 ISnapshot(output).snapshot())

            # Check the objects state are the same after replay
            for jid, obj in keeper.registry.iteritems():
                self.assertEqual(states[jid], obj.snapshot())

        k = DummyJournalKeeper()
        r = journal.RecorderRoot(k)
        o1 = RecordReplayDummy(r)
        o2 = RecordReplayDummy(r)

        d = self.assertAsyncEqual(None, "spam and beans",
                                  o1.spam, "beans")
        d = self.assertAsyncEqual(d, "spam and spam",
                                  o2.spam, "spam")
        d = self.assertAsyncEqual(d, "spam and beans with spam",
                                  o1.spam, "beans", extra="spam")
        d = self.assertAsyncEqual(d, "spam and spam with spam",
                                  o2.spam, "spam", extra="spam")
        d = self.assertAsyncEqual(d, "bacon and eggs followed by "
                                  "spam and bacon with eggs",
                                  o1.double_bacon, "eggs")
        d = self.assertAsyncEqual(d, "bacon and spam followed by "
                                  "spam and bacon with spam",
                                  o2.double_bacon, "spam")
        d = self.assertAsyncEqual(d, ["spam and beans",
                                      "spam and beans with spam",
                                      "bacon and eggs",
                                      "spam and bacon with eggs"],
                                  o1.servings)
        d = self.assertAsyncEqual(d, ["spam and spam",
                                      "spam and spam with spam",
                                      "bacon and spam",
                                      "spam and bacon with spam"],
                                  o2.servings)
        d.addCallback(replay, k)

        return d

    def testNonReentrant(self):
        k = DummyJournalKeeper()
        r = journal.RecorderRoot(k)
        o = ReentrantDummy(r)

        self.assertRaises(journal.ReentrantCallError, o.good)
        self.assertRaises(journal.ReentrantCallError, o.bad)
        d = self.assertAsyncEqual(None, "the ugly", o.ugly)

        return d

    def testErrors(self):
        k = DummyJournalKeeper()
        r = journal.RecorderRoot(k)
        o = ErrorDummy(r)

        self.assertRaises(AttributeError, o.call, "spam")
        self.assertRaises(AttributeError, o.call, "barr")
        self.assertRaises(AttributeError, o.replay, "spam", (None, None))
        self.assertRaises(AttributeError, o.replay, "barr", (None, None))

        self.assertRaises(RecordingResultError, o.bad)
        self.assertRaises(RecordingResultError, o.super_bad)

        self.assertRaises(RecordingResultError, o.call, "bad")
        self.assertRaises(RecordingResultError, o.call, "super_bad")

        d = self.assertAsyncEqual(None, "foo", o.call, "foo")
        d = self.assertAsyncEqual(d, "bar", o.call, "bar")
        d = self.assertAsyncEqual(d, "barr", o.call, "baz")

        d = self.assertAsyncEqual(d, (None, "foo"),
                                  o.replay, "foo", (None, None))
        d = self.assertAsyncEqual(d, (None, "bar"),
                                  o.replay, "bar", (None, None))
        d = self.assertAsyncEqual(d, (None, "barr"),
                                  o.replay, "baz", (None, None))

        return d
