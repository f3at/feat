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
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from feat.common import enum

from . import common


class A(enum.Enum):
    a, b, c = range(3)
    d = 42


class B(enum.Enum):
    a, b, c = range(3)
    d = 666


try:

    string_not_allowed = False

    class C(enum.Enum):
        a = "bad"

except TypeError, e:
    string_not_allowed = True


try:

    same_value_not_allowed = False

    class D(enum.Enum):
        a = 1
        b = 1

except ValueError:
    same_value_not_allowed = True


class TestEnum(common.TestCase):

    def testLogicalValues(self):
        self.assertTrue(A.a)
        self.assertTrue(A.b)
        self.assertTrue(A.c)

    def testConstructor(self):
        self.assertIdentical(A.a, A(A.a))
        self.assertIdentical(A.b, A(A.b))
        self.assertIdentical(A.d, A(A.d))

        self.assertIdentical(A.a, A(0))
        self.assertIdentical(A.b, A(1))
        self.assertIdentical(A.d, A(42))

        self.assertIdentical(B.a, B(B.a))
        self.assertIdentical(B.c, B(B.c))
        self.assertIdentical(B.d, B(B.d))

        self.assertIdentical(B.a, B(0))
        self.assertIdentical(B.c, B(2))
        self.assertIdentical(B.d, B(666))

        self.assertEqual(A.a, A("a"))
        self.assertEqual(A.b, A("b"))
        self.assertEqual(A.d, A("d"))

        self.assertRaises(TypeError, A, 5.2)
        self.assertRaises(TypeError, A, B.a)
        self.assertRaises(KeyError, A, 3)
        self.assertRaises(KeyError, A, "spam")

        self.assertRaises(TypeError, B, 3.14)
        self.assertRaises(TypeError, B, A.d)
        self.assertRaises(KeyError, B, -1)

    def testComparations(self):
        self.assertEqual(A.d, A.d)
        self.assertEqual(A.d, 42)
        self.assertEqual(int(A.a), B.a)
        self.assertNotEqual(int(A.a), None)
        self.assertNotEqual(None, int(A.a))
        self.assertNotEqual(A.a, None)
        self.assertNotEqual(None, A.a)
        self.assertRaises(TypeError, cmp, A.a, B.a)
        self.assertRaises(TypeError, cmp, A.d, B.d)

    def testDictProtocol(self):
        avals = A.values()
        akeys = A.keys()
        aitems = A.items()
        aivals = list(A.itervalues())
        aikeys = list(A.iterkeys())
        aiitems = list(A.iteritems())
        avals.sort()
        akeys.sort()
        aitems.sort()
        aivals.sort()
        aikeys.sort()
        aiitems.sort()

        self.assertEqual(len(A), 4)
        self.assertEqual(avals, ["a", "b", "c", "d"])
        self.assertEqual(avals, aivals)

        self.assertEqual(akeys, [A.a, A.b, A.c, A.d])
        self.assertEqual(akeys, [0, 1, 2, 42])
        self.assertEqual(akeys, aikeys)

        self.assertEqual(aitems, [(0, "a"), (1, "b"), (2, "c"), (42, "d")])
        self.assertEqual(aitems, [(A.a, "a"), (A.b, "b"), (A.c, "c"),
                                  (A.d, "d")])
        self.assertEqual(aitems, aiitems)

        for k in A:
            self.assertTrue(k in A)
        for k in A.keys():
            self.assertTrue(k in A)
        for k in A.iterkeys():
            self.assertTrue(k in A)

        self.assertEqual(A[0], A.a)
        self.assertEqual(A[1], A.b)
        self.assertEqual(A[2], A.c)
        self.assertEqual(A[42], A.d)

        self.assertEqual(A[A.a], A.a)
        self.assertEqual(A[A.b], A.b)
        self.assertEqual(A[A.c], A.c)
        self.assertEqual(A[A.d], A.d)

        self.assertRaises(KeyError, A.__getitem__, 5)
        self.assertRaises(TypeError, A.__getitem__, 5.6)

    def testCasting(self):
        self.assertTrue(B.a in B)
        self.assertTrue(A.a in A)
        try:
            unexpected = B.a in A
            self.fail("Should not be able to cast between enums (%r)"
                      % unexpected)
        except TypeError:
            pass

    def testMetaErrors(self):
        self.assertTrue(string_not_allowed)
        self.assertTrue(same_value_not_allowed)
