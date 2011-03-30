# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from zope.interface import implements

from feat.agents.base import replay
from feat.common.container import *
from feat.common import serialization, journal
from feat.common.serialization import base, pytree
from feat.interface.generic import *
from feat.interface.journal import *

from . import common


@serialization.register
class DummyTimeProvider(serialization.Serializable):

    type_name = "dummy-time-provider"

    implements(ITimeProvider)

    def __init__(self, current=None):
        self.time = current if current is not None else common.time()

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return self.time == other.time

    def __ne__(self, other):
        eq = self.__eq__(other)
        return eq if eq is NotImplemented else not eq

    ### ITimeProvider override ###

    @journal.side_effect
    def get_time(self):
        return self.time

    ### ISerailizable override ###

    def snapshot(self):
        return self.time

    def recover(self, snapshot):
        self.time = snapshot


@serialization.register
class ReplayableTimeProvider(replay.Replayable):

    type_name = "replayable-time-provider"

    implements(ITimeProvider)

    def init_state(self, state, _keeper, current=None):
        state.time = current if current is not None else common.time()
        state.dict = ExpDict(self)
        state.queue = ExpQueue(self)

    @replay.mutable
    def set(self, state, key, value, exp):
        state.dict.set(key, value, exp)

    @replay.mutable
    def add(self, state, value, exp):
        state.queue.add(value, exp)

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        my_state = self._get_state()
        other_state = other._get_state()
        return ((my_state.time == other_state.time)
                and (my_state.dict == other_state.dict)
                and (my_state.queue == other_state.queue))

    def __ne__(self, other):
        eq = self.__eq__(other)
        return eq if eq is NotImplemented else not eq

    ### ITimeProvider override ###

    @journal.side_effect
    @replay.immutable
    def get_time(self, state):
        return state.time


class TestExpDict(common.TestCase):

    def check_iterator(self, iter, expected):
        values = list(iter)
        values.sort()
        expected.sort()
        self.assertEqual(values, expected)

    def testBasicOperations(self):
        d = ExpDict(self)
        d["spam"] = 42
        d["bacon"] = 18
        self.assertTrue("spam" in d)
        self.assertTrue("bacon" in d)
        self.assertEqual(len(d), 2)
        self.assertFalse("beans" in d)
        self.assertEqual(d["spam"], 42)
        self.assertEqual(d["bacon"], 18)
        self.assertEqual(d.get("spam"), 42)
        self.assertEqual(d.get("bacon"), 18)
        self.assertEqual(d.get("spam", 66), 42)
        self.assertEqual(d.get("bacon", 66), 18)
        self.assertEqual(d.get("beans"), None)
        self.assertEqual(d.get("beans", 66), 66)
        self.assertEqual(d.remove("spam"), 42)
        self.assertFalse("spam" in d)
        self.assertEqual(len(d), 1)
        d.set("beans", 88)
        d.set("eggs", 77)
        self.assertTrue("beans" in d)
        self.assertTrue("eggs" in d)
        self.assertEqual(len(d), 3)
        del d["bacon"]
        self.assertFalse("bacon" in d)
        self.assertEqual(len(d), 2)
        d.clear()
        self.assertEqual(len(d), 0)

    def testIterators(self):

        d = ExpDict(self)
        d["spam"] = 42
        d["bacon"] = 18
        d["beans"] = 88
        d["eggs"] = 77

        self.check_iterator(iter(d), ["spam", "bacon", "beans", "eggs"])
        self.check_iterator(d.iterkeys(), ["spam", "bacon", "beans", "eggs"])
        self.check_iterator(d.itervalues(), [42, 18, 88, 77])
        self.check_iterator(d.iteritems(), [("spam", 42), ("bacon", 18),
                                            ("beans", 88), ("eggs", 77)])

    def testComparison(self):
        a = ExpDict(self)
        b = ExpDict(self)
        self.assertEqual(a, b)
        self.assertNotEqual(a, 12)
        self.assertNotEqual(a, {})
        a["spam"] = 12
        self.assertNotEqual(a, b)
        b["spam"] = 24
        self.assertNotEqual(a, b)
        a["spam"] = 24
        self.assertEqual(a, b)
        b[1] = 1
        a[2] = 2
        self.assertNotEqual(a, b)
        b[2] = 2
        a[1] = 1
        self.assertEqual(a, b)

    def testExpiration(self):
        t = DummyTimeProvider(0)
        d = ExpDict(t)
        self.assertEqual(len(d), 0)
        self.assertEqual(d.size(), 0)

        d.set("spam", 42, 0) # Expire right away
        self.assertEqual(d.size(), 0)
        d.set("spam", 42, t.time + 10)
        self.assertEqual(d.size(), 1)
        d.set("bacon", 18, t.time + 20)
        self.assertEqual(d.size(), 2)
        d.set("eggs", 77, t.time + 30)
        self.assertEqual(len(d), 3)
        self.assertEqual(d.size(), 3)

        self.check_iterator(iter(d), ["spam", "bacon", "eggs"])
        self.check_iterator(d.iterkeys(), ["spam", "bacon", "eggs"])
        self.check_iterator(d.itervalues(), [42, 18, 77])
        self.check_iterator(d.iteritems(), [("spam", 42), ("bacon", 18),
                                            ("eggs", 77)])

        t.time += 15
        self.assertEqual(len(d), 2)

        self.check_iterator(iter(d), ["bacon", "eggs"])
        self.check_iterator(d.iterkeys(), ["bacon", "eggs"])
        self.check_iterator(d.itervalues(), [18, 77])
        self.check_iterator(d.iteritems(), [("bacon", 18), ("eggs", 77)])

        self.assertEqual(d.size(), 3)

        t.time += 10
        self.assertEqual(len(d), 1)

        self.check_iterator(iter(d), ["eggs"])
        self.check_iterator(d.iterkeys(), ["eggs"])
        self.check_iterator(d.itervalues(), [77])
        self.check_iterator(d.iteritems(), [("eggs", 77)])

        self.assertEqual(d.size(), 3)

        d.set("beans", 88, t.time + 5)
        d.set("tomatoes", 44, t.time + 5)
        d.set("sausage", 22, t.time + 5)
        d["foo"] = "bar"

        self.assertEqual(len(d), 5)
        self.assertEqual(d.size(), 7)

        t.time += 10
        self.assertEqual(len(d), 1)

        self.check_iterator(iter(d), ["foo"])
        self.check_iterator(d.iterkeys(), ["foo"])
        self.check_iterator(d.itervalues(), ["bar"])
        self.check_iterator(d.iteritems(), [("foo", "bar")])

        self.assertEqual(len(d), 1)
        self.assertEqual(d.size(), 7)
        self.assertRaises(KeyError, d.__getitem__, "spam")
        self.assertEqual(len(d), 1)
        self.assertEqual(d.size(), 6)
        self.assertRaises(KeyError, d.__getitem__, "spam")
        self.assertEqual(len(d), 1)
        self.assertEqual(d.size(), 6)
        self.assertEqual("ohohoh", d.get("bacon", "ohohoh"))
        self.assertEqual(len(d), 1)
        self.assertEqual(d.size(), 5)
        self.assertEqual("ohohoh", d.get("bacon", "ohohoh"))
        self.assertEqual(len(d), 1)
        self.assertEqual(d.size(), 5)
        self.assertRaises(KeyError, d.remove, "eggs")
        self.assertEqual(len(d), 1)
        self.assertEqual(d.size(), 4)
        self.assertRaises(KeyError, d.remove, "eggs")
        self.assertEqual(len(d), 1)
        self.assertEqual(d.size(), 4)

        def del_beans(d):
            del d["beans"]

        self.assertRaises(KeyError, del_beans, d)
        self.assertEqual(len(d), 1)
        self.assertEqual(d.size(), 3)
        self.assertRaises(KeyError, del_beans, d)
        self.assertEqual(len(d), 1)
        self.assertEqual(d.size(), 3)
        self.assertFalse("tomatoes" in d)
        self.assertEqual(len(d), 1)
        self.assertEqual(d.size(), 2)
        self.assertFalse("tomatoes" in d)
        self.assertEqual(len(d), 1)
        self.assertEqual(d.size(), 2)
        d.pack()
        self.assertEqual(len(d), 1)
        self.assertEqual(d.size(), 1)

    def testRelativeExpiration(self):
        t = DummyTimeProvider(0)
        d = ExpDict(t)

        d.set("spam", 42, 10, relative=True)
        d.set("bacon", 18, 20, relative=True)
        d.set("eggs", 77, 30, relative=True)

        self.check_iterator(iter(d), ["spam", "bacon", "eggs"])
        t.time += 15
        self.check_iterator(iter(d), ["bacon", "eggs"])
        t.time += 10
        self.check_iterator(iter(d), ["eggs"])
        t.time += 10
        self.check_iterator(iter(d), [])

    def testForcedExpiration(self):
        t = DummyTimeProvider(0)
        d = ExpDict(t, 3)
        self.assertEqual(len(d), 0)
        d.set("spam", 42, 10, relative=True)
        d.set("bacon", 18, 40, relative=True)
        d.set("eggs", 77, 40, relative=True)
        self.assertEqual(len(d), 3)
        self.assertEqual(d.size(), 3)
        t.time += 15
        self.assertEqual(len(d), 2)
        d.set("beans", 88, 5, relative=True)
        self.assertEqual(len(d), 3)
        self.assertEqual(d.size(), 4)
        self.assertEqual(77, d["eggs"]) # Forced packing
        self.assertEqual(d.size(), 3)
        t.time += 10
        self.assertEqual(len(d), 2)
        d.set("1", 1, 5, relative=True)
        self.assertEqual(len(d), 3)
        self.assertEqual(d.size(), 4)
        d.set("2", 2, 5, relative=True) # Forced packing
        self.assertEqual(len(d), 4)
        self.assertEqual(d.size(), 4)
        d.set("3", 3, 5, relative=True) # nothing to pack
        self.assertEqual(len(d), 5)
        self.assertEqual(d.size(), 5)
        t.time += 10
        self.assertEqual(len(d), 2)
        self.assertEqual(d.remove("eggs"), 77) # forced pack
        self.assertEqual(len(d), 1)
        self.assertEqual(d.size(), 1)
        t.time += 10
        self.assertEqual(len(d), 0)
        d.set("1", 1, 0.1, relative=True)
        d.set("2", 2, 0.1, relative=True)
        d.set("3", 3, 0.1, relative=True)
        self.assertEqual(len(d), 3)
        self.assertEqual(d.size(), 4)
        self.assertTrue("2" in d) # forced pack
        self.assertEqual(len(d), 3)
        self.assertEqual(d.size(), 3)
        t.time += 0.2
        self.assertEqual(len(d), 0)
        self.assertFalse("foo" in d) # Only one lazy packing per second
        self.assertEqual(d.size(), 3)
        d.set("4", 1, 0.8, relative=True)
        d.set("5", 2, 0.9, relative=True)
        d.set("6", 3, 0.9, relative=True)
        self.assertEqual(d.size(), 6)
        t.time += 0.8
        self.assertFalse("foo" in d) # Now it should lazy pack
        self.assertEqual(d.size(), 2)
        t.time += 0.2
        d.pack() # calling pack() always pack
        self.assertEqual(d.size(), 0)

    def testSerialization(self):
        t = DummyTimeProvider(0)
        serialize = pytree.serialize
        unserialize = pytree.unserialize
        Ins = pytree.Instance

        d = ExpDict(t)
        self.assertEqual(serialize(d),
                         Ins("xdict",
                             (Ins("dummy-time-provider", 0), {})))
        self.assertEqual(d, unserialize(serialize(d)))
        d["foo"] = 1
        d.set("bar", 2, 5)
        d.set("spam", 3, 8.001)
        d.set("bacon", 4, 8.0012)
        self.assertEqual(d, unserialize(serialize(d)))
        self.assertEqual(serialize(d),
                         Ins("xdict", (Ins("dummy-time-provider", 0),
                                       {"foo": (None, 1),
                                        "bar": (5000, 2),
                                        "spam": (8001, 3),
                                        "bacon": (8001, 4)})))


class TestExpQueue(common.TestCase):

    def check_iterator(self, iter, expected):
        values = list(iter)
        values.sort()
        expected.sort()
        self.assertEqual(values, expected)

    def testBasicOperations(self):
        q = ExpQueue(self)
        self.assertRaises(Empty, q.pop)
        q.add("spam")
        q.add("bacon")
        q.add("eggs")
        self.check_iterator(iter(q), ["spam", "bacon", "eggs"])
        self.assertEqual(len(q), 3)
        # Without expiration no order guaranteed
        self.assertTrue(q.pop() in ["spam", "bacon", "eggs"])
        self.assertEqual(len(q), 2)
        self.assertTrue(q.pop() in ["spam", "bacon", "eggs"])
        self.assertEqual(len(q), 1)
        q.clear()
        self.assertEqual(len(q), 0)
        self.assertRaises(Empty, q.pop)

    def testComparison(self):
        a = ExpQueue(self)
        b = ExpQueue(self)
        self.assertEqual(a, b)
        self.assertNotEqual(a, 12)
        self.assertNotEqual(a, [])
        a.add("foo")
        self.assertNotEqual(a, b)
        b.add("bar")
        self.assertNotEqual(a, b)
        b.add("foo")
        a.add("bar")
        self.assertEqual(a, b)

    def testExpiration(self):
        t = DummyTimeProvider(0)
        q = ExpQueue(t)
        self.assertEqual(q.size(), 0)

        q.add(1, 0) # Expire right away
        self.assertEqual(q.size(), 0)
        q.add(1, t.time + 10)
        q.add(2, t.time + 20)
        q.add(3, t.time + 30)
        self.assertEqual(q.size(), 3)
        self.assertEqual(len(q), 3)
        self.check_iterator(iter(q), [1, 2, 3])
        t.time += 15
        self.assertEqual(len(q), 2)
        self.check_iterator(iter(q), [2, 3])
        self.assertEqual(q.size(), 3)
        t.time += 10
        self.assertEqual(len(q), 1)
        self.check_iterator(iter(q), [3])
        self.assertEqual(q.size(), 3)

        q.add(4, t.time + 5)
        q.add(5, t.time + 5)
        q.add(6, t.time + 5)
        q.add(7)

        self.assertEqual(len(q), 5)
        self.assertEqual(q.size(), 7)

        t.time += 10
        self.assertEqual(len(q), 1)
        self.check_iterator(iter(q), [7])
        self.assertEqual(q.size(), 7)

        self.assertEqual(q.pop(), 7)
        self.assertEqual(len(q), 0)
        self.assertEqual(q.size(), 0)

    def testRelativeExpiration(self):
        t = DummyTimeProvider(0)
        q = ExpQueue(t)
        self.assertEqual(q.size(), 0)
        q.add(1, 10, relative=True)
        q.add(2, 20, relative=True)
        q.add(3, 30, relative=True)
        self.assertEqual(q.size(), 3)
        self.assertEqual(len(q), 3)
        self.check_iterator(iter(q), [1, 2, 3])
        t.time += 15
        self.assertEqual(len(q), 2)
        self.check_iterator(iter(q), [2, 3])
        self.assertEqual(q.size(), 3)
        t.time += 10
        self.assertEqual(len(q), 1)
        self.check_iterator(iter(q), [3])
        self.assertEqual(q.size(), 3)
        q.clear()
        self.assertEqual(len(q), 0)
        self.assertEqual(q.size(), 0)

    def testPriorities(self):
        t = DummyTimeProvider(0)
        q = ExpQueue(t)
        q.add(1, None)
        q.add(2, 1.5)
        q.add(3, 0.5)
        q.add(4, 10)
        q.add(5, 5)
        q.add(6, 6.5)
        q.add(7, None)
        q.add(8, 2.5)

        self.assertEqual(q.pop(), 3)
        self.assertEqual(q.pop(), 2)
        self.assertEqual(q.pop(), 8)
        self.assertEqual(q.pop(), 5)
        self.assertEqual(q.pop(), 6)
        self.assertEqual(q.pop(), 4)
        self.assertTrue(q.pop() in [1, 7])
        self.assertTrue(q.pop() in [1, 7])
        self.assertRaises(Empty, q.pop)

    def testForcedExpiration(self):
        t = DummyTimeProvider(0)
        q = ExpQueue(t, 3)
        self.assertEqual(len(q), 0)
        q.add(1, 10, relative=True)
        q.add(2, 40, relative=True)
        q.add(3, 45, relative=True)
        self.assertEqual(len(q), 3)
        self.assertEqual(q.size(), 3)

        t.time += 15
        self.assertEqual(len(q), 2)
        q.add(4, 5, relative=True)
        self.assertEqual(len(q), 3)
        self.assertEqual(q.size(), 4)
        q.add(5, 10, relative=True) # Forced packing
        self.assertEqual(len(q), 4)
        self.assertEqual(q.size(), 4)

        t.time += 5
        self.assertEqual(len(q), 3)
        self.assertEqual(q.size(), 4)

        t.time += 5
        self.assertEqual(len(q), 2)
        self.assertEqual(q.size(), 4)
        q.add(6, 5, relative=True) # Force packing
        self.assertEqual(len(q), 3)
        self.assertEqual(q.size(), 3)
        q.add(7, 0.1, relative=True)
        q.add(8, 0.1, relative=True)
        self.assertEqual(len(q), 5)
        self.assertEqual(q.size(), 5)

        t.time += 0.2
        self.assertEqual(len(q), 3)
        self.assertEqual(q.size(), 5)
        q.add(9, 5, relative=True) # No more than one lazy packing per second
        self.assertEqual(len(q), 4)
        self.assertEqual(q.size(), 6)

        t.time += 0.6
        self.assertEqual(len(q), 4)
        self.assertEqual(q.size(), 6)
        self.assertEqual(q.pop(), 6) # Forced packing
        self.assertEqual(len(q), 3)
        self.assertEqual(q.size(), 3)
        q.add(10, 0.1, relative=True)
        self.assertEqual(len(q), 4)
        self.assertEqual(q.size(), 4)

        t.time += 0.2
        self.assertEqual(len(q), 3)
        self.assertEqual(q.size(), 4)
        q.pack() # pack() always force packing
        self.assertEqual(len(q), 3)
        self.assertEqual(q.size(), 3)

        self.assertEqual(q.pop(), 9)
        self.assertEqual(q.pop(), 2)
        self.assertEqual(q.pop(), 3)

    def testSerialization(self):
        t = DummyTimeProvider(0)
        serialize = pytree.serialize
        unserialize = pytree.unserialize
        Ins = pytree.Instance

        d = ExpQueue(t)
        self.assertEqual(serialize(d),
                         Ins("xqueue",
                             (Ins("dummy-time-provider", 0), [])))
        self.assertEqual(d, unserialize(serialize(d)))
        d.add(1)
        d.add(2, 5)
        d.add(3, 9.001)
        d.add(4, 8.0012)
        self.assertEqual(d, unserialize(serialize(d)))
        self.assertEqual(serialize(d),
                         Ins("xqueue", (Ins("dummy-time-provider", 0),
                                        [(5000, 2),
                                         (8001, 4),
                                         (9001, 3),
                                         (None, 1)])))


class TestReplayability(common.TestCase):

    def setUp(self):
        self.externalizer = serialization.Externalizer()
        self.serializer = pytree.Serializer(externalizer=self.externalizer)
        self.unserializer = pytree.Unserializer(externalizer=self.externalizer)
        self.keeper = journal.StupidJournalKeeper(self.serializer,
                                                  self.unserializer)
        self.externalizer.add(self.keeper)

    def serialize(self, value):
        return self.serializer.convert(value)

    def unserialize(self, value):
        return self.unserializer.convert(value)

    def testDictWithReplay(self):
        t = ReplayableTimeProvider(self.keeper, 0)
        t.set("spam", 3, 8.001)
        t.set("bacon", 4, 8.0012)
        self.assertEqual(t, self.unserialize(self.serialize(t)))
