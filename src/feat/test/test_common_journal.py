# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.
#-*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from twisted.trial.unittest import FailTest
from zope.interface import implements

from feat.common import journal, fiber, defer, serialization, reflect
from feat.common.serialization import pytree
from feat.interface.journal import *
from feat.interface.serialization import *

from . import common
from feat.interface.fiber import TriggerType


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
        f.add_callback(common.break_chain)
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
                f.add_callback(common.break_chain)
            f.add_callback(a)
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
        self.some_foo = 0
        self.some_bar = 0
        self.some_baz = 0

    @journal.recorded()
    def foo(self, value):
        self.some_foo += value
        return self.some_foo

    @journal.recorded()
    def bar(self, value, minus=0):
        self.some_bar += value - minus
        return self.some_bar

    @journal.recorded()
    def barr(self, minus=0):
        self.some_bar -= minus
        return self.some_bar

    @journal.recorded()
    def baz(self, value):
        f = fiber.Fiber()
        f.add_callback(self.async_add)
        f.succeed(value)
        return f

    def async_add(v):
        self.some_baz += v
        return self.some_baz

    @journal.recorded()
    def bazz(self, value):
        '''To test second level'''
        return self.baz(value)


class RecordReplayDummy(journal.Recorder):

    def __init__(self, parent):
        journal.Recorder.__init__(self, parent)
        self.reset()

    def reset(self):
        self.servings = []

    def snapshot(self):
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
        f.add_callback(self.spam, extra=accompaniment)
        f.add_callback(self._prepare_double, serving)
        f.succeed("bacon")
        return f

    @journal.recorded()
    def _addServing(self, serving):
        '''Normally called only by other recorded functions'''
        self.servings.append(serving)
        return serving

    def _prepare_double(self, second_serving, first_serving):
        """Should not modify state, because it's not journalled"""
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

    @journal.recorded(reentrant=False)
    def async_ugly(self):
        f = fiber.Fiber()
        f.add_callback(common.break_chain)
        f.add_callback(self.ugly)
        return f.succeed()


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


try:

    class DuplicatedErrorDummy1(journal.Recorder):

        @journal.recorded()
        def spam(self):
            pass

        @journal.recorded()
        def spam(self):
            pass

        duplicated_function_error1 = False

except RuntimeError:
    duplicated_function_error1 = True


try:

    class DuplicatedErrorDummy2(journal.Recorder):

        @journal.recorded("foo")
        def spam(self):
            pass

        @journal.recorded("foo")
        def bacon(self):
            pass

        duplicated_function_error2 = False

except RuntimeError:
    duplicated_function_error2 = True


# Used to inspect what side-effect code got really called
_effect_calls = []


@journal.side_effect
def spam_effect(accomp, extra=None):
    global _effect_calls
    _effect_calls.append("spam_effect")
    extra_desc = extra and (" with " + extra) or ""
    return ("spam and %s%s followed by %s"
            % (accomp, extra_desc, bacon_effect("spam", extra=extra)))


@journal.side_effect
def bacon_effect(accomp, extra=None):
    global _effect_calls
    _effect_calls.append("bacon_effect")
    extra_desc = extra and (" with " + extra) or ""
    return "bacon and %s%s" % (accomp, extra_desc)


def fun_without_effect(obj):
    global _effect_calls
    _effect_calls.append("fun_without_effect")
    return fun_with_effect(obj)


@journal.side_effect
def fun_with_effect(obj):
    global _effect_calls
    _effect_calls.append("fun_with_effect")
    return obj.meth_without_effect()


@journal.side_effect
def bad_effect1():
    return defer.succeed(None)


@journal.side_effect
def bad_effect2():
    f = fiber.Fiber()
    f.succeed(None)
    return f


@journal.side_effect
def bad_effect3():
    return bad_effect1()


def bad_effect4():
    return bad_effect2()


@journal.side_effect
def bad_replay_effect(*args, **kwargs):
    return "ok"


@serialization.register
class SideEffectsDummy(serialization.Serializable):

    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return self.name == other.name

    def __ne__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return not self.__eq__(other)

    @journal.side_effect
    def beans_effect(self, accomp, extra=None):
        global _effect_calls
        _effect_calls.append("beans_effect")
        extra_desc = extra and (" with " + extra) or ""
        return ("%s beans and %s%s followed by %s"
                % (self.name, accomp, extra_desc,
                   self.eggs_effect("spam", extra=extra)))

    @journal.side_effect
    def eggs_effect(self, accomp, extra=None):
        global _effect_calls
        _effect_calls.append("eggs_effect")
        extra_desc = extra and (" with " + extra) or ""
        return "%s eggs and %s%s" % (self.name, accomp, extra_desc)

    @journal.side_effect
    def test_effect(self):
        global _effect_calls
        _effect_calls.append("test_effect")
        return fun_without_effect(self)

    def meth_without_effect(self):
        global _effect_calls
        _effect_calls.append("meth_without_effect")
        return self.meth_with_effect()

    @journal.side_effect
    def meth_with_effect(self):
        global _effect_calls
        _effect_calls.append("meth_with_effect")
        return "ok"


class A(journal.Recorder):

    @journal.recorded()
    def foo(self):
        return "A.foo"

    def bar(self):
        return "A.bar"


class B(A):

    @journal.recorded()
    def foo(self):
        return "B.foo+" + A.foo(self)

    @journal.recorded()
    def bar(self):
        return "B.bar+" + A.bar(self)


class C(A):

    @journal.recorded()
    def foo(self):
        return "C.foo+" + A.foo(self)

    @journal.recorded()
    def bar(self):
        return "C.bar+" + A.bar(self)


class ExceptionTestDummy(journal.Recorder):

    @journal.recorded()
    def type_error_1(self):
        1 + ""

    @journal.recorded()
    def type_error_2(self):
        try:
            1 + ""
        except:
            return fiber.fail()

    @journal.recorded()
    def type_error_3(self):
        f = fiber.Fiber()
        f.add_callback(self._async_type_error)
        f.add_both(self._check_for_replay)
        return f.succeed()

    @journal.recorded()
    def type_error_4(self):
        f = fiber.Fiber()
        f.add_callback(common.delay, 0.1)
        f.add_callback(self._async_type_error)
        f.add_both(self._check_for_replay)
        return f.succeed()

    def _async_type_error(self, _):
        1 + ""

    @journal.recorded()
    def _check_for_replay(self, f):
        if not f.check(TypeError):
            raise FailTest("Expecting TypeError, got %s" % f.type.__name__)
        f.trap(ValueError)


class TestJournaling(common.TestCase):

    def setUp(self):
        self.serializer = pytree.Serializer()
        self.unserializer = pytree.Unserializer()
        self.keeper = journal.StupidJournalKeeper(self.serializer,
                                                  self.unserializer)

    def freeze(self, value):
        return self.serializer.freeze(value)

    def new_entry(self, fun_id, *args, **kwargs):
        return self.keeper.new_entry(None, fun_id, *args, **kwargs)

    @defer.inlineCallbacks
    def testExceptions(self):
        R = journal.RecorderRoot(self.keeper, base_id="test")
        a = ExceptionTestDummy(R)
        yield self.assertFails(TypeError, a.type_error_1)
        yield self.assertFails(TypeError, a.type_error_2)
        yield self.assertFails(TypeError, a.type_error_3)
        yield self.assertFails(TypeError, a.type_error_4)

    def testInheritence(self):
        R = journal.RecorderRoot(self.keeper, base_id="test")
        a = A(R)
        b = B(R)
        c = C(R)

        d = defer.succeed(None)

        d = self.assertAsyncEqual(d, "A.foo", a.foo)
        d = self.assertAsyncEqual(d, "B.foo+A.foo", b.foo)
        d = self.assertAsyncEqual(d, "C.foo+A.foo", c.foo)

        d = self.assertAsyncEqual(d, "A.bar", a.bar)
        d = self.assertAsyncEqual(d, "B.bar+A.bar", b.bar)
        d = self.assertAsyncEqual(d, "C.bar+A.bar", c.bar)

        return d

    def testJournalId(self):
        R = journal.RecorderRoot(self.keeper, base_id="test")
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

        R = journal.RecorderRoot(self.keeper)
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

            spam_id = "feat.test.test_common_journal.BasicRecordingDummy.spam"
            bacon_id = "bacon"

            break_call = ((reflect.canonical_name(common.break_chain),
                           None, None), None)

            expected = [[iid, spam_id, ("beans", ), None,
                         [], "spam and beans"],

                        [iid, spam_id, ("beans", ), {"extra": "spam"},
                         [], "spam and beans with spam"],

                        [iid, bacon_id, ("beans", ), None,
                         [], (TriggerType.succeed,
                                "spam and beans",
                                [break_call])],
                        [iid, bacon_id, ("beans", ), {"extra": "spam"},
                         [], (TriggerType.succeed,
                                "spam and beans with spam",
                                [break_call])]]

            self.assertEqual(expected, records)

        root = journal.RecorderRoot(self.keeper)
        obj = BasicRecordingDummy(root)
        self.assertEqual(obj, self.keeper.lookup(obj.journal_id))
        d = self.assertAsyncEqual(None, "spam and beans",
                                  obj.spam, "beans")
        d = self.assertAsyncEqual(d, "spam and beans with spam",
                                  obj.spam, "beans", extra="spam")
        d = self.assertAsyncEqual(d, "spam and beans",
                                  obj.async_spam, "beans")
        d = self.assertAsyncEqual(d, "spam and beans with spam",
                                  obj.async_spam, "beans", extra="spam")
        return d.addCallback(check_records, self.keeper.get_records())

    def testFiberInfo(self):

        def check_fid_and_filter(records):
            fid = records[0][1]
            for record in records:
                self.assertEqual(fid, record[1])
            return fid, [(r[0], r[2]) for r in records]

        def check_records(_, records):

            test_id = "feat.test.test_common_journal.FiberInfoDummy.test"
            fun1a_id = "feat.test.test_common_journal.FiberInfoDummy.fun1a"
            fun1b_id = "feat.test.test_common_journal.FiberInfoDummy.fun1b"
            fun2a_id = "feat.test.test_common_journal.FiberInfoDummy.fun2a"
            fun2b_id = "feat.test.test_common_journal.FiberInfoDummy.fun2b"
            fun3_id = "feat.test.test_common_journal.FiberInfoDummy.fun3"

            records = [r[1:4] for r in records]

            # Used to ensure all fibers have different identifier
            fids = set()

            # obj.fun3, only one entry
            entries, records = records[:1], records[1:]
            fid, entries = check_fid_and_filter(entries)
            self.assertFalse(fid in fids)
            fids.add(fid)
            self.assertEqual([(fun3_id, 0)], entries)

            # obj.fun2a, 3 entries
            entries, records = records[:3], records[3:]
            fid, entries = check_fid_and_filter(entries)
            self.assertFalse(fid in fids)
            fids.add(fid)
            self.assertEqual([(fun2a_id, 0), (fun3_id, 1),
                              (fun3_id, 1)], entries)

            # obj.fun1a, 7 entries
            entries, records = records[:7], records[7:]
            fid, entries = check_fid_and_filter(entries)
            self.assertFalse(fid in fids)
            fids.add(fid)
            self.assertEqual([(fun1a_id, 0),
                              (fun2a_id, 1), (fun3_id, 2), (fun3_id, 2),
                              (fun2b_id, 1), (fun3_id, 2),
                              (fun3_id, 2)], entries)

            # obj.test, 15 entries
            entries, records = records[:15], records[15:]
            fid, entries = check_fid_and_filter(entries)
            self.assertFalse(fid in fids)
            fids.add(fid)
            self.assertEqual([(test_id, 0),
                              (fun1a_id, 1),
                              (fun2a_id, 2), (fun3_id, 3), (fun3_id, 3),
                              (fun2b_id, 2), (fun3_id, 3), (fun3_id, 3),
                              (fun1b_id, 1),
                              (fun2a_id, 2), (fun3_id, 3), (fun3_id, 3),
                              (fun2b_id, 2), (fun3_id, 3),
                              (fun3_id, 3)], entries)

        d = defer.succeed(None)

        # Test with "synchronous" fibers where callbacks are called right away
        root = journal.RecorderRoot(self.keeper)
        obj = FiberInfoDummy(root, False)
        d.addCallback(obj.fun3)
        d.addCallback(obj.fun2a)
        d.addCallback(obj.fun1a)
        d.addCallback(obj.test)
        d.addCallback(check_records, self.keeper.get_records())

        # test with "real" asynchronous fibers
        root = journal.RecorderRoot(self.keeper)
        obj = FiberInfoDummy(root, True)
        d.addCallback(obj.fun3)
        d.addCallback(obj.fun2a)
        d.addCallback(obj.fun1a)
        d.addCallback(obj.test)
        d.addCallback(check_records, self.keeper.get_records())

        return d

    def testNestedRecordedFunction(self):

        def check_records(_, records):
            self.assertEqual(5, len(records))
            expected = [39, # ((3 + 5) + 7) + (3 + 5)) + ((3 + 5) + (3 + 5))
                        23, # ((3 + 5) + 7) + (3 + 5)
                        16, # (3 + 5) + (3 + 5)
                        15, # (3 + 5) + 7
                         8] # 3 + 5
            self.assertEqual(expected, [r[7] for r in records]),

        root = journal.RecorderRoot(self.keeper)
        obj = NestedRecordedDummy(root)

        d = defer.succeed(None)
        d.addCallback(defer.drop_param, obj.main, 3, 5)
        d.addCallback(defer.drop_param, obj.funA, 3, 5)
        d.addCallback(defer.drop_param, obj.funB, 3, 5)
        d.addCallback(defer.drop_param, obj.funC, 3, 5)
        d.addCallback(defer.drop_param, obj.funD, 3, 5)
        d.addCallback(check_records, self.keeper.get_records())

        return d

    def testDirectReplay(self):

        base_id = "feat.test.test_common_journal."
        foo_id = base_id + "DirectReplayDummy.foo"
        bar_id = base_id + "DirectReplayDummy.bar"
        barr_id = base_id + "DirectReplayDummy.barr"
        baz_id = base_id + "DirectReplayDummy.baz"
        bazz_id = base_id + "DirectReplayDummy.bazz"

        async_add_id = base_id + "DirectReplayDummy.async_add"

        r = journal.RecorderRoot(self.keeper)
        o = DirectReplayDummy(r)
        self.assertEqual(o.some_foo, 0)
        self.assertEqual(o.some_bar, 0)
        self.assertEqual(o.some_baz, 0)

        self.assertEqual(3, o.replay(self.new_entry(foo_id, 3)))
        self.assertEqual(3, o.some_foo)
        self.assertEqual(6, o.replay(self.new_entry(foo_id, 3)))
        self.assertEqual(6, o.some_foo)

        self.assertEqual(2, o.replay(self.new_entry(bar_id, 2)))
        self.assertEqual(2, o.some_bar)
        self.assertEqual(4, o.replay(self.new_entry(bar_id, 2)))
        self.assertEqual(4, o.some_bar)
        self.assertEqual(5, o.replay(self.new_entry(bar_id, 2, minus=1)))
        self.assertEqual(5, o.some_bar)
        self.assertEqual(3, o.replay(self.new_entry(barr_id, minus=2)))
        self.assertEqual(3, o.some_bar)
        self.assertEqual(2, o.replay(self.new_entry(barr_id, minus=1)))
        self.assertEqual(2, o.some_bar)

        # Test that fibers are not executed
        self.assertEqual((TriggerType.succeed, 5,
                          [((async_add_id, None, None), None)]),
                         self.freeze(o.replay(self.new_entry(baz_id, 5))))
        self.assertEqual(0, o.some_baz)
        self.assertEqual((TriggerType.succeed, 8,
                          [((async_add_id, None, None), None)]),
                          self.freeze(o.replay(self.new_entry(baz_id, 8))))
        self.assertEqual(0, o.some_baz)
        self.assertEqual((TriggerType.succeed, 5,
                          [((async_add_id, None, None), None)]),
                          self.freeze(o.replay(self.new_entry(bazz_id, 5))))
        self.assertEqual(0, o.some_baz)
        self.assertEqual((TriggerType.succeed, 8,
                          [((async_add_id, None, None), None)]),
                          self.freeze(o.replay(self.new_entry(bazz_id, 8))))
        self.assertEqual(0, o.some_baz)

    def testRecordReplay(self):

        def replay(_, keeper):
            # Keep objects states and reset before replaying
            states = {}
            for obj in keeper.iter_recorders():
                states[obj.journal_id] = obj.snapshot()
                obj.reset()

            # Replaying
            for entry in keeper.iter_entries():
                obj = keeper.lookup(entry.journal_id)
                self.assertTrue(obj is not None)
                output = obj.replay(entry)
                self.assertRaises(ReplayError, entry.next_side_effect, "dummy")
                self.assertEqual(entry.frozen_result, self.freeze(output))

            # Check the objects state are the same after replay
            for obj in keeper.iter_recorders():
                self.assertEqual(states[obj.journal_id], obj.snapshot())

        r = journal.RecorderRoot(self.keeper)
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
        d.addCallback(replay, self.keeper)

        return d

    def testNonReentrant(self):
        r = journal.RecorderRoot(self.keeper)
        o = ReentrantDummy(r)

        d = defer.succeed(None)

        d = self.assertAsyncFailure(d, [ReentrantCallError], o.good)
        d = self.assertAsyncFailure(d, [ReentrantCallError], o.bad)
        d = self.assertAsyncEqual(None, "the ugly", o.ugly)
        d = self.assertAsyncFailure(d, [ReentrantCallError], o.async_ugly)

        return d

    @common.attr(skip=
                 "TODO: this behavior is switched off as a WIP on updates")
    def testErrors(self):
        # Check initialization errors
        self.assertTrue(duplicated_function_error1)
        self.assertTrue(duplicated_function_error2)

        r = journal.RecorderRoot(self.keeper)
        o = ErrorDummy(r)

        wrong1_id = "feat.test.test_common_journal.ErrorDummy.spam"
        wrong2_id = "feat.test.test_common_journal.ErrorDummy.barr"

        foo_id = "feat.test.test_common_journal.ErrorDummy.foo"
        bar_id = "feat.test.test_common_journal.ErrorDummy.bar"
        barr_id = "baz" # Customized ID
        bad_id = "feat.test.test_common_journal.ErrorDummy.bad"
        super_bad_id = "feat.test.test_common_journal.ErrorDummy.super_bad"

        # Recording with wrong function identifier
        self.assertRaises(AttributeError, o.record, wrong1_id)
        self.assertRaises(AttributeError, o.record, wrong2_id)

        # Calling wrong function

        def wrong_fun():
            pass

        self.assertRaises(AttributeError, o.call, wrong_fun)

        # Replaying with wrong function identifier
        self.assertRaises(AttributeError, o.replay,
                          self.keeper.new_entry(None, wrong1_id))
        self.assertRaises(AttributeError, o.replay,
                          self.keeper.new_entry(None, wrong2_id))

        d = defer.succeed(None)

        d = self.assertAsyncFailure(d, [RecordingResultError], o.bad)
        d = self.assertAsyncFailure(d, [RecordingResultError], o.super_bad)

        d = self.assertAsyncFailure(d, [RecordingResultError],
                                    o.record, bad_id)
        d = self.assertAsyncFailure(d, [RecordingResultError],
                                    o.record, super_bad_id)

        d = self.assertAsyncEqual(None, "foo", o.record, foo_id)
        d = self.assertAsyncEqual(d, "bar", o.record, bar_id)
        d = self.assertAsyncEqual(d, "barr", o.record, barr_id)

        d = self.assertAsyncEqual(d, "foo", o.replay,
                                  self.keeper.new_entry(None, foo_id))
        d = self.assertAsyncEqual(d, "bar", o.replay,
                                  self.keeper.new_entry(None, bar_id))
        d = self.assertAsyncEqual(d, "barr", o.replay,
                                  self.keeper.new_entry(None, barr_id))

        return d

    def testSideEffectsErrors(self):
        # Tests outside recording context
        self.assertRaises(SideEffectResultError, bad_effect1)
        self.assertRaises(SideEffectResultError, bad_effect2)
        self.assertRaises(SideEffectResultError, bad_effect3)
        self.assertRaises(SideEffectResultError, bad_effect4)

        # Setup a recording environment
        section = fiber.WovenSection()
        section.enter()
        entry = self.new_entry("dummy")
        section.state[journal.RECMODE_TAG] = JournalMode.recording
        section.state[journal.JOURNAL_ENTRY_TAG] = entry
        section.state[journal.RECORDING_TAG] = True

        self.assertRaises(SideEffectResultError, bad_effect1)
        self.assertRaises(SideEffectResultError, bad_effect2)
        self.assertRaises(SideEffectResultError, bad_effect3)
        self.assertRaises(SideEffectResultError, bad_effect4)

        section.abort()

        # Setup a replay environment
        section = fiber.WovenSection()
        section.enter()
        funid = "feat.test.test_common_journal.bad_replay_effect"

        entry = self.new_entry("dummy")
        entry.add_side_effect(funid, "ok", 42, 18)
        entry.add_side_effect(funid, "ok", extra="foo")
        entry.add_side_effect(funid, "ok", 42, 18, extra="foo")
        entry.add_side_effect(funid, "ok")
        entry.add_side_effect(funid, "ok")
        entry.add_side_effect(funid, "ok")
        entry.add_side_effect(funid, "ok")

        section.state[journal.RECMODE_TAG] = JournalMode.replay
        section.state[journal.JOURNAL_ENTRY_TAG] = entry

        self.assertEqual("ok", bad_replay_effect(42, 18))
        self.assertEqual("ok", bad_replay_effect(extra="foo"))
        self.assertEqual("ok", bad_replay_effect(42, 18, extra="foo"))
        self.assertEqual("ok", bad_replay_effect())
        self.assertRaises(ReplayError, bad_replay_effect, 42)
        self.assertRaises(ReplayError, bad_replay_effect, extra=18)
        self.assertRaises(ReplayError, bad_effect1)
        self.assertRaises(ReplayError, bad_replay_effect)

        section.abort()

    def testSideEffectsFunctionCalls(self):
        global _effect_calls
        _effect_calls = []
        spam_effect_id = "feat.test.test_common_journal.spam_effect"
        bacon_effect_id = "feat.test.test_common_journal.bacon_effect"

        # Tests outside recording context
        del _effect_calls[:]
        self.assertEqual(bacon_effect("eggs", extra="spam"),
                         "bacon and eggs with spam")
        self.assertEqual(_effect_calls, ["bacon_effect"])

        del _effect_calls[:]
        self.assertEqual(spam_effect("spam", extra="beans"),
                         "spam and spam with beans followed by "
                         "bacon and spam with beans")
        self.assertEqual(_effect_calls, ["spam_effect", "bacon_effect"])

        # Tests inside recording context
        section = fiber.WovenSection()
        section.enter()
        entry = self.new_entry("dummy")
        section.state[journal.RECMODE_TAG] = JournalMode.recording
        section.state[journal.JOURNAL_ENTRY_TAG] = entry

        del _effect_calls[:]
        self.assertEqual(bacon_effect("spam", extra="eggs"),
                         "bacon and spam with eggs")
        self.assertEqual(_effect_calls, ["bacon_effect"])
        self.assertEqual(entry.next_side_effect(bacon_effect_id,
                                                "spam", extra="eggs"),
                         "bacon and spam with eggs")

        del _effect_calls[:]
        self.assertEqual(spam_effect("beans", extra="spam"),
                         "spam and beans with spam followed by "
                         "bacon and spam with spam")
        self.assertEqual(_effect_calls, ["spam_effect", "bacon_effect"])
        self.assertEqual(entry.next_side_effect(spam_effect_id,
                                                "beans", extra="spam"),
                           "spam and beans with spam followed by "
                           "bacon and spam with spam")

        section.abort()

        # Test in replay context
        section = fiber.WovenSection()
        section.enter()
        section.state[journal.RECMODE_TAG] = JournalMode.replay
        section.state[journal.JOURNAL_ENTRY_TAG] = entry

        entry.rewind_side_effects()

        del _effect_calls[:]
        self.assertEqual(bacon_effect("spam", extra="eggs"),
                         "bacon and spam with eggs")
        self.assertEqual(_effect_calls, []) # Nothing got called

        del _effect_calls[:]
        self.assertEqual(spam_effect("beans", extra="spam"),
                         "spam and beans with spam followed by "
                         "bacon and spam with spam")
        self.assertEqual(_effect_calls, []) # Nothing got called

        section.abort()

    def testSideEffectsMethodCalls(self):
        global _effect_calls
        _effect_calls = []
        beans_effect_id = "feat.test.test_common_journal." \
                          "SideEffectsDummy.beans_effect"
        eggs_effect_id = "feat.test.test_common_journal." \
                         "SideEffectsDummy.eggs_effect"

        obj = SideEffectsDummy("chef's")

        # Tests outside recording context
        del _effect_calls[:]
        self.assertEqual(obj.eggs_effect("spam", extra="bacon"),
                         "chef's eggs and spam with bacon")
        self.assertEqual(_effect_calls, ["eggs_effect"])

        del _effect_calls[:]
        self.assertEqual(obj.beans_effect("spam", extra="eggs"),
                         "chef's beans and spam with eggs followed by "
                         "chef's eggs and spam with eggs")
        self.assertEqual(_effect_calls, ["beans_effect", "eggs_effect"])

        # Tests inside recording context
        section = fiber.WovenSection()
        section.enter()
        entry = self.new_entry("dummy")
        section.state[journal.RECMODE_TAG] = JournalMode.recording
        section.state[journal.JOURNAL_ENTRY_TAG] = entry

        del _effect_calls[:]
        self.assertEqual(obj.eggs_effect("spam", extra="bacon"),
                         "chef's eggs and spam with bacon")
        self.assertEqual(_effect_calls, ["eggs_effect"])
        self.assertEqual(entry.next_side_effect(eggs_effect_id,
                                                "spam", extra="bacon"),
                           "chef's eggs and spam with bacon")

        del _effect_calls[:]
        self.assertEqual(obj.beans_effect("spam", extra="eggs"),
                         "chef's beans and spam with eggs followed by "
                         "chef's eggs and spam with eggs")
        self.assertEqual(_effect_calls, ["beans_effect", "eggs_effect"])
        self.assertEqual(entry.next_side_effect(beans_effect_id,
                                                "spam", extra="eggs"),
                           "chef's beans and spam with eggs followed by "
                           "chef's eggs and spam with eggs")

        section.abort()

        # Test in replay context
        section = fiber.WovenSection()
        section.enter()
        section.state[journal.RECMODE_TAG] = JournalMode.replay
        section.state[journal.JOURNAL_ENTRY_TAG] = entry

        entry.rewind_side_effects()

        del _effect_calls[:]
        self.assertEqual(obj.eggs_effect("spam", extra="bacon"),
                         "chef's eggs and spam with bacon")
        self.assertEqual(_effect_calls, []) # Nothing got called

        del _effect_calls[:]
        self.assertEqual(obj.beans_effect("spam", extra="eggs"),
                         "chef's beans and spam with eggs followed by "
                         "chef's eggs and spam with eggs")
        self.assertEqual(_effect_calls, []) # Nothing got called

        section.abort()

    def testCallChain(self):
        global _effect_calls
        _effect_calls = []
        fun_with_id = "feat.test.test_common_journal.fun_with_effect"
        fun_without_id = "feat.test.test_common_journal.fun_without_effect"
        meth_test_id = "feat.test.test_common_journal." \
                       "SideEffectsDummy.test_effect"
        meth_with_id = "feat.test.test_common_journal." \
                       "SideEffectsDummy.meth_with_effect"
        meth_without_id = "feat.test.test_common_journal." \
                          "SideEffectsDummy.meth_without_effect"

        obj = SideEffectsDummy("dummy")

        # test outside of any reocrding context

        del _effect_calls[:]
        self.assertEqual("ok", obj.test_effect())
        self.assertEqual(["test_effect", "fun_without_effect",
                          "fun_with_effect", "meth_without_effect",
                          "meth_with_effect"], _effect_calls)

        del _effect_calls[:]
        self.assertEqual("ok", fun_without_effect(obj))
        self.assertEqual(["fun_without_effect",
                          "fun_with_effect", "meth_without_effect",
                          "meth_with_effect"], _effect_calls)

        del _effect_calls[:]
        self.assertEqual("ok", fun_with_effect(obj))
        self.assertEqual(["fun_with_effect", "meth_without_effect",
                          "meth_with_effect"], _effect_calls)

        del _effect_calls[:]
        self.assertEqual("ok", obj.meth_without_effect())
        self.assertEqual(["meth_without_effect",
                          "meth_with_effect"], _effect_calls)

        del _effect_calls[:]
        self.assertEqual("ok", obj.meth_with_effect())
        self.assertEqual(["meth_with_effect"], _effect_calls)

        # Test from inside a recording context
        section = fiber.WovenSection()
        section.enter()
        section.state[journal.RECMODE_TAG] = JournalMode.recording

        entry = self.new_entry("dummy")
        section.state[journal.JOURNAL_ENTRY_TAG] = entry

        del _effect_calls[:]
        self.assertEqual("ok", obj.test_effect())
        self.assertEqual(["test_effect", "fun_without_effect",
                          "fun_with_effect", "meth_without_effect",
                          "meth_with_effect"], _effect_calls)
        self.assertEqual(entry.next_side_effect(meth_test_id), "ok")

        del _effect_calls[:]
        self.assertEqual("ok", fun_without_effect(obj))
        self.assertEqual(["fun_without_effect",
                          "fun_with_effect", "meth_without_effect",
                          "meth_with_effect"], _effect_calls)
        self.assertEqual(entry.next_side_effect(fun_with_id, obj), "ok")

        del _effect_calls[:]
        self.assertEqual("ok", fun_with_effect(obj))
        self.assertEqual(["fun_with_effect", "meth_without_effect",
                          "meth_with_effect"], _effect_calls)
        self.assertEqual(entry.next_side_effect(fun_with_id, obj), "ok")

        del _effect_calls[:]
        self.assertEqual("ok", obj.meth_without_effect())
        self.assertEqual(["meth_without_effect",
                          "meth_with_effect"], _effect_calls)
        self.assertEqual(entry.next_side_effect(meth_with_id), "ok")

        del _effect_calls[:]
        self.assertEqual("ok", obj.meth_with_effect())
        self.assertEqual(["meth_with_effect"], _effect_calls)
        self.assertEqual(entry.next_side_effect(meth_with_id), "ok")

        section.abort()

        # Test from inside a replay context
        # Test from inside a recording context
        section = fiber.WovenSection()
        section.enter()
        section.state[journal.RECMODE_TAG] = JournalMode.replay
        section.state[journal.JOURNAL_ENTRY_TAG] = entry

        entry.rewind_side_effects()

        del _effect_calls[:]
        self.assertEqual("ok", obj.test_effect())
        self.assertEqual([], _effect_calls) # Nothing called

        del _effect_calls[:]
        self.assertEqual("ok", fun_without_effect(obj))
        self.assertEqual(["fun_without_effect"], _effect_calls)

        del _effect_calls[:]
        self.assertEqual("ok", fun_with_effect(obj))
        self.assertEqual([], _effect_calls) # Nothing called

        del _effect_calls[:]
        self.assertEqual("ok", obj.meth_without_effect())
        self.assertEqual(["meth_without_effect"], _effect_calls)

        del _effect_calls[:]
        self.assertEqual("ok", obj.meth_with_effect())
        self.assertEqual([], _effect_calls) # Nothing called

        section.abort()

    def testSerialization(self):
        root = journal.RecorderRoot(self.keeper, "dummy")
        obj = BasicRecordingDummy(root)
        sub = BasicRecordingDummy(obj)

        root2 = journal.RecorderRoot.restore(root.snapshot())
        self.assertEqual(root.journal_keeper, root2.journal_keeper)
        # Check that the identifier generator has not been reset
        self.assertNotEqual(obj.journal_id,
                            BasicRecordingDummy(root2).journal_id)

        obj2 = BasicRecordingDummy.restore(obj.snapshot())
        self.assertEqual(obj.journal_keeper, obj2.journal_keeper)
        self.assertEqual(obj.journal_parent, obj2.journal_parent)
        self.assertEqual(obj.journal_id, obj2.journal_id)
        # Check that the identifier generator has not been reset
        self.assertNotEqual(sub.journal_id,
                            BasicRecordingDummy(obj2).journal_id)
