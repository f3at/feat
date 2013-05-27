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
# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from zope.interface import implements

from feat.agents.base import replay
from feat.common.container import *
from feat.common import container
from feat.common import serialization, journal, time
from feat.common.serialization import base, pytree
from feat.interface.generic import *
from feat.interface.journal import *

from . import common


@serialization.register
class DummyTimeProvider(serialization.Serializable):

    type_name = "dummy-time-provider"

    implements(ITimeProvider)

    def __init__(self, current=None):
        self.time = current if current is not None else time.time()

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
        state.time = current if current is not None else time.time()
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
        size = ExpDict.DEFAULT_MAX_SIZE

        d = ExpDict(t)
        self.assertEqual(serialize(d),
                         Ins("xdict", (Ins("dummy-time-provider", 0), size,
                             {})))
        self.assertEqual(d, unserialize(serialize(d)))
        d["foo"] = 1
        d.set("bar", 2, 5)
        d.set("spam", 3, 8.001)
        d.set("bacon", 4, 8.0012)
        self.assertEqual(d, unserialize(serialize(d)))
        self.assertEqual(serialize(d),
                         Ins("xdict", (Ins("dummy-time-provider", 0), size,
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

    def testOnExpireCallback(self):

        class Listener(object):

            def on_expire(self, element):
                self.expired.append(element)

            @property
            def expired(self):
                if not hasattr(self, '_expired'):
                    self._expired = list()
                return self._expired

        listener = Listener()

        t = DummyTimeProvider(0)
        q = ExpQueue(t, on_expire=listener.on_expire)
        q.add("spam", 10)
        q.add("bacon", 20)
        q.add("eggs", 30)
        q.add("beans", 23)
        self.check_iterator(iter(q), ["spam", "bacon", "beans", "eggs"])
        q.pack()
        self.assertEqual([], listener.expired)

        t.time += 15
        self.check_iterator(iter(q), ["bacon", "beans", "eggs"])
        q.pack()
        self.assertEqual(["spam"], listener.expired)

        t.time += 10
        eggs = q.pop()
        self.assertEqual('eggs', eggs)
        self.assertEqual(["spam", "bacon", "beans"], listener.expired)
        self.check_iterator(iter(q), [])

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


def create_classes():

    class A(object):

        registry = MroDict('_mro_registry')
        stack = MroList('_mro_stack')
        dol = MroDictOfList('_mro_dol')

    class B(A):
        pass

    class C(A):
        pass

    class D(B):
        pass

    return A, B, C, D


class TestMroDict(common.TestCase):

    def testItWorks(self):
        A, B, C, D = create_classes()

        A.registry['spam'] = 'a'
        A.registry['eggs'] = 'a'
        B.registry['spam'] = 'b'
        C.registry['spam'] = 'c'
        D.registry['spam'] = 'd'
        D.registry['eggs'] = 'd'

        self.assertEqual(A.registry['spam'], 'a')
        self.assertEqual(B.registry['spam'], 'b')
        self.assertEqual(C.registry['spam'], 'c')
        self.assertEqual(D.registry['spam'], 'd')

        self.assertEqual(A.registry['eggs'], 'a')
        self.assertEqual(B.registry['eggs'], 'a')
        self.assertEqual(C.registry['eggs'], 'a')
        self.assertEqual(D.registry['eggs'], 'd')

        # it should also work on instances not classes
        a = A()
        self.assertEqual(a.registry['spam'], 'a')
        self.assertEqual(a.registry['eggs'], 'a')

        self.assertEqual(dict(A.registry), {"spam": "a", "eggs": "a"})
        self.assertEqual(dict(B.registry), {"spam": "b", "eggs": "a"})
        self.assertEqual(dict(C.registry), {"spam": "c", "eggs": "a"})
        self.assertEqual(dict(D.registry), {"spam": "d", "eggs": "d"})


class TestMroList(common.TestCase):

    def testItWorksS(self):
        A, B, C, D = create_classes()

        A.stack.append("SPAM")
        A.stack.append("egg")
        B.stack.extend(["bacon", "spam"])
        C.stack.append("spam")
        C.stack.append("sausage")
        D.stack.extend(["tomato", "beans"])

        self.assertEqual(len(A.stack), 2)
        self.assertEqual(len(B.stack), 4)
        self.assertEqual(len(C.stack), 4)
        self.assertEqual(len(D.stack), 6)

        self.assertEqual(A.stack[0], "SPAM")
        self.assertEqual(A.stack[-1], "egg")
        self.assertEqual(B.stack[0], "SPAM")
        self.assertEqual(B.stack[-1], "spam")
        self.assertEqual(C.stack[0], "SPAM")
        self.assertEqual(C.stack[-1], "sausage")
        self.assertEqual(D.stack[0], "SPAM")
        self.assertEqual(D.stack[-1], "beans")

        self.assertTrue("egg" in A.stack)
        self.assertFalse("bacon" in A.stack)
        self.assertFalse("sausage" in A.stack)
        self.assertFalse("tomato" in A.stack)

        self.assertTrue("egg" in B.stack)
        self.assertTrue("bacon" in B.stack)
        self.assertFalse("sausage" in B.stack)
        self.assertFalse("tomato" in B.stack)

        self.assertTrue("egg" in C.stack)
        self.assertFalse("bacon" in C.stack)
        self.assertTrue("sausage" in C.stack)
        self.assertFalse("tomato" in C.stack)

        self.assertTrue("egg" in D.stack)
        self.assertTrue("bacon" in D.stack)
        self.assertFalse("sausage" in D.stack)
        self.assertTrue("tomato" in D.stack)

        self.assertEqual(list(A.stack), ["SPAM", "egg"])
        self.assertEqual(list(B.stack), ["SPAM", "egg", "bacon", "spam"])
        self.assertEqual(list(C.stack), ["SPAM", "egg", "spam", "sausage"])
        self.assertEqual(list(D.stack),
                         ["SPAM", "egg", "bacon", "spam", "tomato", "beans"])


class TestMroDictOfList(common.TestCase):

    def testItWorksS(self):
        A, B, C, D = create_classes()

        A.dol.put("spam", 1)
        A.dol.put("egg", 8)
        B.dol.aggregate("bacon", [4, 7])
        B.dol.put("spam", 3)
        C.dol.put("sausage", 9)
        C.dol.put("egg", 2)
        D.dol.put("bacon", 5)
        D.dol.put("egg", 6)
        D.dol.put("tomato", 0)

        self.assertTrue("spam" in A.dol)
        self.assertTrue("egg" in A.dol)
        self.assertFalse("bacon" in A.dol)
        self.assertFalse("sausage" in A.dol)
        self.assertFalse("tomato" in A.dol)

        self.assertTrue("spam" in B.dol)
        self.assertTrue("egg" in B.dol)
        self.assertTrue("bacon" in B.dol)
        self.assertFalse("sausage" in B.dol)
        self.assertFalse("tomato" in B.dol)

        self.assertTrue("spam" in C.dol)
        self.assertTrue("egg" in C.dol)
        self.assertFalse("bacon" in C.dol)
        self.assertTrue("sausage" in C.dol)
        self.assertFalse("tomato" in C.dol)

        self.assertTrue("spam" in D.dol)
        self.assertTrue("egg" in D.dol)
        self.assertTrue("bacon" in D.dol)
        self.assertFalse("sausage" in D.dol)
        self.assertTrue("tomato" in D.dol)

        self.assertEqual(len(A.dol), 2)
        self.assertEqual(len(B.dol), 3)
        self.assertEqual(len(C.dol), 3)
        self.assertEqual(len(D.dol), 4)

        self.assertEqual(A.dol["spam"], [1])
        self.assertEqual(B.dol["spam"], [1, 3])
        self.assertEqual(C.dol["spam"], [1])
        self.assertEqual(D.dol["spam"], [1, 3])

        self.assertEqual(A.dol["egg"], [8])
        self.assertEqual(B.dol["egg"], [8])
        self.assertEqual(C.dol["egg"], [8, 2])
        self.assertEqual(D.dol["egg"], [8, 6])

        self.assertEqual(set(iter(A.dol)), set(["spam", "egg"]))
        self.assertEqual(set(iter(B.dol)), set(["spam", "egg", "bacon"]))
        self.assertEqual(set(C.dol.iterkeys()),
                         set(["spam", "egg", "sausage"]))
        self.assertEqual(set(D.dol.iterkeys()),
                         set(["spam", "egg", "bacon", "tomato"]))

        self.assertEqual(set([(k, tuple(v)) for k, v in D.dol.iteritems()]),
                         set([("spam", (1, 3)),
                              ("egg", (8, 6)),
                              ("bacon", (4, 7, 5)),
                              ("tomato", (0, ))]))

        self.assertEqual(set([tuple(v) for v in C.dol.itervalues()]),
                         set([(1, ), (8, 2), (9, )]))

        self.assertEqual(dict(A.dol), {"spam": [1], "egg": [8]})
        self.assertEqual(dict(B.dol), {"spam": [1, 3], "egg": [8],
                                       "bacon": [4, 7]})
        self.assertEqual(dict(C.dol), {"spam": [1], "egg": [8, 2],
                                       "sausage": [9]})
        self.assertEqual(dict(D.dol), {"spam": [1, 3], "egg": [8, 6],
                                       "bacon": [4, 7, 5], "tomato": [0]})


class TestRunningAverage(common.TestCase):

    def testItWorks(self):
        av = container.RunningAverage(100)
        self.assertEqual(100, av.get_value())

        av.add_point(3)
        self.assertEqual(3, av.get_value())
        av.add_point(5)
        self.assertEqual(4, av.get_value())
        av.add_point(20)
        self.assertEqual((28.0/3), av.get_value())
        av.add_point(0)
        self.assertEqual((28.0/4), av.get_value())
