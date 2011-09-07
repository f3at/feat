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

from feat.common import guard

from feat.interface.serialization import *

from . import common
from twisted.trial.unittest import SkipTest


class Dummy(guard.Guarded):

    def init_state(self, state):
        state.value = 0

    @guard.mutable
    def double(self, state, value, minus=None):
        result = value * 2
        if minus is not None:
            result -= minus
        state.value += result
        return result

    @guard.immutable
    def get_value(self, state):
        return state.value


class FreezeDummy(object):

    def __init__(self):
        self.simple_bool = True
        self.simple_int = 42
        self.simple_str = "dummy"
        self.simple_list = [1, 2, 3]
        self.simple_tuple = (2, 3, 4)
        self.simple_dict = {7: 14, 8: 16, 9: 18}
        self.simple_set = set([1, 5, 9])

        self.combined_list = [1, [2, 3], 4]
        self.combined_tuple = (1, [2, 3], 4)


class TopFreezeDummy(FreezeDummy):

    def __init__(self):
        FreezeDummy.__init__(self)
        self.reference = FreezeDummy()
        self.list_ref = [1, FreezeDummy(), 3]
        self.tuple_ref = (1, FreezeDummy(), 3)


class TestStateGuard(common.TestCase):

    def testBasicGuarded(self):
        obj = Dummy()
        self.assertEqual(obj.get_value(), 0)
        self.assertEqual(obj.double(2), 4)
        self.assertEqual(obj.get_value(), 4)
        self.assertEqual(obj.double(3, minus=1), 5)
        self.assertEqual(obj.get_value(), 9)

    def testSerialization(self):
        obj = Dummy()
        self.assertEqual(obj.get_value(), 0)
        self.assertEqual(obj.double(4, minus=1), 7)
        self.assertEqual(obj.get_value(), 7)
        state = ISerializable(obj).snapshot()
        obj2 = Dummy.restore(state)
        self.assertIsNot(obj, obj2)
        self.assertEqual(obj2.get_value(), 7)
        self.assertEqual(obj.double(2, minus=3), 1)
        self.assertEqual(obj2.get_value(), 8)

    def testFreeze(self):

        def testNotFrozen(obj):
            self.assertEqual(obj.simple_bool, True)
            obj.simple_bool = False
            self.assertEqual(obj.simple_bool, False)

            self.assertEqual(obj.simple_int, 42)
            obj.simple_int = 18
            self.assertEqual(obj.simple_int, 18)

            self.assertEqual(obj.simple_str, "dummy")
            obj.simple_str = "spam"
            self.assertEqual(obj.simple_str, "spam")

            self.assertEqual(obj.simple_list, [1, 2, 3])
            obj.simple_list = [2, 4, 6]
            self.assertEqual(obj.simple_list, [2, 4, 6])
            obj.simple_list.append(8)
            self.assertEqual(obj.simple_list, [2, 4, 6, 8])
            obj.simple_list.pop(0)
            self.assertEqual(obj.simple_list, [4, 6, 8])
            del obj.simple_list[:]
            self.assertEqual(obj.simple_list, [])

            self.assertEqual(obj.simple_tuple, (2, 3, 4))
            obj.simple_tuple = (4, 6, 8)
            self.assertEqual(obj.simple_tuple, (4, 6, 8))

            self.assertEqual(obj.simple_dict, {7: 14, 8: 16, 9: 18})
            obj.simple_dict = {7: 7, 8: 8}
            self.assertEqual(obj.simple_dict, {7: 7, 8: 8})
            obj.simple_dict[9] = 9
            self.assertEqual(obj.simple_dict, {7: 7, 8: 8, 9: 9})
            obj.simple_dict.pop(8)
            self.assertEqual(obj.simple_dict, {7: 7, 9: 9})
            obj.simple_dict.clear()
            self.assertEqual(obj.simple_dict, {})

            self.assertEqual(obj.simple_set, set([1, 5, 9]))
            obj.simple_set = set([7, 5, 3])
            self.assertEqual(obj.simple_set, set([7, 5, 3]))
            obj.simple_set.add(8)
            self.assertEqual(obj.simple_set, set([7, 5, 3, 8]))
            obj.simple_set.remove(5)
            self.assertEqual(obj.simple_set, set([7, 3, 8]))
            obj.simple_set.clear()
            self.assertEqual(obj.simple_set, set())

            self.assertEqual(obj.combined_list, [1, [2, 3], 4])
            obj.combined_list[1].append(5)
            self.assertEqual(obj.combined_list, [1, [2, 3, 5], 4])
            obj.combined_list[1] = 66
            self.assertEqual(obj.combined_list, [1, 66, 4])

            self.assertEqual(obj.combined_tuple, (1, [2, 3], 4))
            obj.combined_tuple[1].append(5)
            self.assertEqual(obj.combined_tuple, (1, [2, 3, 5], 4))

        def testFrozen(obj):

            def set(attr, value):
                self.assertRaises(AttributeError, setattr, obj, attr, value)

            def raises(fun, *args, **kwargs):
                self.assertRaises(AttributeError, fun, *args, **kwargs)

            self.assertEqual(obj.simple_bool, True)
            set("simple_bool", False)
            self.assertEqual(obj.simple_bool, True)

            self.assertEqual(obj.simple_int, 42)
            set("simple_int", 18)
            self.assertEqual(obj.simple_int, 42)

            self.assertEqual(obj.simple_str, "dummy")
            set("simple_str", "spam")
            self.assertEqual(obj.simple_str, "dummy")

            self.assertEqual(obj.simple_tuple, (2, 3, 4))
            set("simple_tuple", (4, 6, 8))
            self.assertEqual(obj.simple_tuple, (2, 3, 4))
            self.assertEqual(obj.simple_tuple, (2, 3, 4))

            def check_list(l, expected):
                # Expected to work
                self.assertEqual(l, expected)
                self.assertEqual(l[0], expected[0])
                self.assertEqual(l[:-1], expected[:-1])
                self.assertTrue(expected[0] in l)

                # Expected to fail
                raises(l.append, 8)
                raises(l.remove, 1)
                raises(l.pop, 0)
                raises(l.extend, [6])
                raises(l.insert, 0, 0)
                raises(l.reverse)
                raises(l.sort)
                raises(l.__delitem__, 0)
                raises(l.__delslice__, 0, -1)
                raises(l.__setitem__, 0, None)
                raises(l.__setslice__, 0, 0, [9])

                # Didn't change
                self.assertEqual(l, expected)

            check_list(obj.simple_list, [1, 2, 3])
            set("simple_list", [2, 4, 6])
            self.assertEqual(obj.simple_list, [1, 2, 3])

            def check_dict(d, expected):
                # Expected to work
                self.assertEqual(d, expected)
                k = expected.keys()[0]
                self.assertEqual(d[k], expected[k])
                self.assertEqual(d.get(k), expected[k])
                self.assertEqual(d.get("NOT IN THERE"), None)
                self.assertTrue(k in d)

                # Expected to fail
                raises(d.pop, 8)
                raises(d.popitem, 8)
                raises(d.update, {10: 20})
                raises(d.clear)
                raises(d.__setitem__, 10, 20)
                raises(d.__delitem__, 8)
                self.assertEqual(d, expected)

            check_dict(obj.simple_dict, {7: 14, 8: 16, 9: 18})
            set("simple_dict", {7: 7, 8: 8})
            self.assertEqual(obj.simple_dict, {7: 14, 8: 16, 9: 18})

            def check_set(s, expected):
                # Expected to work
                self.assertEqual(s, expected)
                i = list(s)[0]
                self.assertTrue(i in s)

                # Expected to fail
                raises(s.pop, 8)
                raises(s.add, 10)
                raises(s.update, set([12]))
                raises(s.remove, 7)
                raises(s.discard, 7)
                raises(s.clear)
                self.assertEqual(s, expected)

            check_set(obj.simple_set, set([1, 5, 9]))
            set("simple_set", set([4, 5, 6]))
            self.assertEqual(obj.simple_set, set([1, 5, 9]))

            self.assertEqual(obj.combined_list, [1, [2, 3], 4])
            check_list(obj.combined_list[1], [2, 3])
            self.assertEqual(obj.combined_list, [1, [2, 3], 4])

            self.assertEqual(obj.combined_tuple, (1, [2, 3], 4))
            check_list(obj.combined_tuple[1], [2, 3])
            self.assertEqual(obj.combined_tuple, (1, [2, 3], 4))

        # test non-frozen as reference
        obj = TopFreezeDummy()
        testNotFrozen(obj)
        testNotFrozen(obj.reference)
        obj.reference = None
        self.assertEqual(None, obj.reference)
        testNotFrozen(obj.list_ref[1])
        testNotFrozen(obj.tuple_ref[1])

        obj = guard.freeze(TopFreezeDummy())
        testFrozen(obj)
        testFrozen(obj.reference)
        self.assertRaises(AttributeError, setattr, obj, "reference", None)
        testFrozen(obj.list_ref[1])
        testFrozen(obj.tuple_ref[1])

    testFreeze.skip = "State freeze not implemented yet"
