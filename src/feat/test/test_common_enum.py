# -*- Mode: Python; test-case-name: flumotion.test.test_fileutils -*-
# vi:si:et:sw=4:sts=4:ts=4

from twisted.trial import unittest
from feat.common import enum


class A(enum.Enum):
    a, b, c = range(3)
    d = 42


class B(enum.Enum):
    a, b, c = range(3)
    d = 666


class TestEnum(unittest.TestCase):

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
        self.assertEqual(aitems, [(A.a, "a"), (A.b, "b"), (A.c, "c"), (A.d, "d")])
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

