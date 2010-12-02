# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import types

from twisted.spread import jelly

from feat.common import serialization, reflect
from feat.interface.serialization import *

from . import common


class A(serialization.Serializable):

    def __init__(self, x):
        self.x = x


class B(A):

    def __init__(self, x, y):
        A.__init__(self, x)
        self.y = y


class C(serialization.Serializable):

    type_name = "Custom"

    def __init__(self, z):
        self.z = z


class D(serialization.Serializable):

    type_name = "D"

    def __init__(self, u):
        self.u = u

    def recover(self, u, context=None):
        self.u = u

    def snapshot(self, context=None):
        return self.u


class E(D):

    def __init__(self, u, v):
        D.__init__(self, u)
        self.v = v

    def recover(self, snapshot, context=None):
        u, self.v = snapshot
        D.recover(self, u, context)

    def snapshot(self, context=None):
        return D.snapshot(self, context), self.v


class TestSerializable(common.TestCase):

    def testTypename(self):
        self.assertEqual(A.type_name, __name__ + "." + "A")
        self.assertEqual(B.type_name, __name__ + "." + "B")
        self.assertEqual(C.type_name, "Custom")
        self.assertEqual(D.type_name, "D")
        self.assertEqual(E.type_name, __name__ + "." + "E")

        a = A(42)
        b = B(12, 18)
        c = C(66)
        d = D(1)
        e = E(2, 3)

        self.assertEqual(a.type_name, __name__ + "." + "A")
        self.assertEqual(b.type_name, __name__ + "." + "B")
        self.assertEqual(c.type_name, "Custom")
        self.assertEqual(d.type_name, "D")
        self.assertEqual(e.type_name, __name__ + "." + "E")

    def testSnapshot(self):
        a = A(42)
        self.assertEqual(a.x, 42)
        self.assertEqual(a.snapshot(), {"x": 42})

        b = B(12, 18)
        self.assertEqual(b.x, 12)
        self.assertEqual(b.y, 18)
        self.assertEqual(b.snapshot(), {"x": 12, "y": 18})

        c = C(66)
        self.assertEqual(c.z, 66)
        self.assertEqual(c.snapshot(), {"z": 66})

        d = D(1)
        self.assertEqual(d.u, 1)
        self.assertEqual(d.snapshot(), 1)

        e = E(2, 3)
        self.assertEqual(e.u, 2)
        self.assertEqual(e.v, 3)
        self.assertEqual(e.snapshot(), (2, 3))

    def testRestore(self):
        a = A.restore({"x": 42})
        self.assertEqual(a.x, 42)

        b = B.restore({"x": 12, "y": 18})
        self.assertEqual(b.x, 12)
        self.assertEqual(b.y, 18)

        c = C.restore({"z": 66})
        self.assertEqual(c.z, 66)

        d = D.restore(1)
        self.assertEqual(d.u, 1)

        e = E.restore((2, 3))
        self.assertEqual(e.u, 2)
        self.assertEqual(e.v, 3)

    def testSnapshotRestore(self):
        a1 = A(42)
        a2 = A.restore(a1.snapshot())
        self.assertEqual(a2.x, 42)
        self.assertNotEqual(a1, a2)

        b1 = B(12, 18)
        b2 = B.restore(b1.snapshot())
        self.assertEqual(b2.x, 12)
        self.assertEqual(b2.y, 18)
        self.assertNotEqual(b1, b2)

        c1 = C(66)
        c2 = C.restore(c1.snapshot())
        self.assertEqual(c2.z, 66)
        self.assertNotEqual(c1, c2)

        d1 = D(1)
        d2 = D.restore(d1.snapshot())
        self.assertEqual(d2.u, 1)
        self.assertNotEqual(d1, d2)

        e1 = E(2, 3)
        e2 = E.restore(e1.snapshot())
        self.assertEqual(e2.u, 2)
        self.assertEqual(e2.v, 3)
        self.assertNotEqual(e1, e2)
