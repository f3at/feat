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


class BasicSerializableDummy(serialization.Serializable, jelly.Jellyable):

    def __init__(self):
        self.str = "dummy"
        self.unicode = u"dummy"
        self.int = 42
        self.long = 2**66
        self.float = 3.1415926
        self.bool = True
        self.none = None
        self.list = [1, 2, 3]
        self.tuple = (1, 2, 3)
        self.set = set([1, 2, 3])
        self.dict = {1: 2, 3: 4}

    def getStateFor(self, jellyer):
        return self.__dict__


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


class BaseSerializerTest(common.TestCase):

    def checkPackingValue(self, fun_name, value, expected):
        direct_fun = getattr(self.serializer, fun_name)
        # Directly calling the correct packing method
        self.assertEqual(direct_fun(value), expected)
        # Calling the generic packing method
        self.assertEqual(self.serializer.pack_value(value), expected)
        # Calling serialization method
        self.assertEqual(self.serializer.serialize(value), expected)
        return direct_fun

    def checkPackingAlmostValue(self, fun_name, value, expected):
        direct_fun = getattr(self.serializer, fun_name)
        # Directly calling the correct packing method
        self.assertAlmostEqual(direct_fun(value), expected)
        # Calling the generic packing method
        self.assertAlmostEqual(self.serializer.pack_value(value), expected)
        # Calling serialization method
        self.assertAlmostEqual(self.serializer.serialize(value), expected)
        return direct_fun

    def checkPackingType(self, fun_name, value, exp_type):
        direct_fun = getattr(self.serializer, fun_name)
        # Directly calling the correct packing method
        self.assertEqual(type(direct_fun(value)), exp_type)
        # Calling the generic packing method
        self.assertEqual(type(self.serializer.pack_value(value)), exp_type)
        # Calling serialization method
        self.assertEqual(type(self.serializer.serialize(value)), exp_type)

    def checkPackingMutability(self, fun_name, value):
        direct_fun = getattr(self.serializer, fun_name)
        # Check value is being copied
        self.assertNotEqual(id(direct_fun(value)), id(value))
        self.assertNotEqual(id(self.serializer.pack_value(value)), id(value))
        self.assertNotEqual(id(self.serializer.serialize(value)), id(value))


class TestTreeSerializer(BaseSerializerTest):

    def setUp(self):
        self.serializer = serialization.TreeSerializer()

    def testBasicImmutablePacking(self):
        self.checkPackingValue("pack_str", "dummy", "dummy")
        self.checkPackingValue("pack_unicode", u"dummy", u"dummy")
        self.checkPackingValue("pack_unicode", u"áéí", u"áéí")
        self.checkPackingValue("pack_int", 42, 42)
        self.checkPackingValue("pack_long", 2**66, 2**66)
        self.checkPackingAlmostValue("pack_float", 3.1415926, 3.1415926)
        self.checkPackingValue("pack_bool", True, True)
        self.checkPackingValue("pack_none", None, None)

        self.checkPackingType("pack_str", "dummy", str)
        self.checkPackingType("pack_unicode", u"dummy", unicode)
        self.checkPackingType("pack_int", 42, int)
        self.checkPackingType("pack_long", 2**66, long)
        self.checkPackingType("pack_float", 3.1415926, float)
        self.checkPackingType("pack_bool", True, bool)
        self.checkPackingType("pack_none", None, types.NoneType)

    def testBasicMutablePacking(self):
        self.checkPackingValue("pack_tuple", (), ())
        self.checkPackingValue("pack_tuple", (1, 2, 3), (1, 2, 3))
        self.checkPackingValue("pack_list", [], [])
        self.checkPackingValue("pack_list", [1, 2, 3], [1, 2, 3])
        self.checkPackingValue("pack_set", set([]), set([]))
        self.checkPackingValue("pack_set", set([1, 3]), set([1, 3]))
        self.checkPackingValue("pack_dict", {}, {})
        self.checkPackingValue("pack_dict", {1: 2, 3: 4}, {1: 2, 3: 4})

        self.checkPackingType("pack_tuple", (), tuple)
        self.checkPackingType("pack_tuple", (1, 2, 3), tuple)
        self.checkPackingType("pack_list", [], list)
        self.checkPackingType("pack_list", [1, 2, 3], list)
        self.checkPackingType("pack_set", set([]), set)
        self.checkPackingType("pack_set", set([1, 3]), set)
        self.checkPackingType("pack_dict", {}, dict)
        self.checkPackingType("pack_dict", {1: 2, 3: 4}, dict)

        # WARNING, the empty tuple is a singleton so it doesn't pass
        # the mutable check, doing the basic one instead
        self.checkPackingMutability("pack_tuple", (1, 2, 3))
        self.checkPackingMutability("pack_list", [])
        self.checkPackingMutability("pack_list", [1, 2, 3])
        self.checkPackingMutability("pack_set", set([]))
        self.checkPackingMutability("pack_set", set([1, 3]))
        self.checkPackingMutability("pack_dict", {})
        self.checkPackingMutability("pack_dict", {1: 2, 3: 4})

    def testBasicTreePacking(self):

        def check(value, result):
            if isinstance(value, int):
                self.assertTrue(isinstance(result, int))
                return

            self.assertNotEqual(id(value), id(result))
            self.assertEqual(type(value), type(result))
            self.assertEqual(value, result)

            if isinstance(value, dict):
                for k in value:
                    self.assertTrue(k in result)
                    # Extract result key
                    rk = filter(lambda v: v == k, result.keys())[0]
                    check(k, rk)
                    check(value[k], result[rk])
            else:
                values = list(value)
                results = list(result)
                for v, r in zip(values, results):
                    check(v, r)

        value = [1,
                 (1, (2, 3), [4, 5], set([6, 7]), {8: 9}),
                 [1, (2, 3), [4, 5], set([6, 7]), {8: 9}],
                 set([1, (2, 3)]),
                 {1: (2, 3), 4: [5, 6], 7: set([8, 9]),
                  10: {11: 12}, (13, 14): 15}]

        check(value, self.serializer.pack_value(value))
        check(value, self.serializer.serialize(value))

    def testBasicInstancePacking(self):

        def check(value, result):
            self.assertTrue(IInstance.providedBy(result))
            self.assertEqual(result.type_name, reflect.canonical_name(value))

            self.assertEqual(value.str, result.snapshot["str"])
            self.assertEqual(value.unicode, result.snapshot["unicode"])
            self.assertEqual(value.int, result.snapshot["int"])
            self.assertEqual(value.long, result.snapshot["long"])
            self.assertAlmostEqual(value.float, result.snapshot["float"])
            self.assertEqual(value.bool, result.snapshot["bool"])
            self.assertEqual(value.none, result.snapshot["none"])
            self.assertEqual(value.tuple, result.snapshot["tuple"])
            self.assertEqual(value.list, result.snapshot["list"])
            self.assertEqual(value.set, result.snapshot["set"])
            self.assertEqual(value.dict, result.snapshot["dict"])

            self.assertEqual(type(value.str),
                             type(result.snapshot["str"]))
            self.assertEqual(type(value.unicode),
                             type(result.snapshot["unicode"]))
            self.assertEqual(type(value.int),
                             type(result.snapshot["int"]))
            self.assertEqual(type(value.long),
                             type(result.snapshot["long"]))
            self.assertEqual(type(value.float),
                             type(result.snapshot["float"]))
            self.assertEqual(type(value.bool),
                             type(result.snapshot["bool"]))
            self.assertEqual(type(value.none),
                             type(result.snapshot["none"]))
            self.assertEqual(type(value.tuple),
                             type(result.snapshot["tuple"]))
            self.assertEqual(type(value.list),
                             type(result.snapshot["list"]))
            self.assertEqual(type(value.set),
                             type(result.snapshot["set"]))
            self.assertEqual(type(value.dict),
                             type(result.snapshot["dict"]))

            self.assertNotEqual(id(value.tuple),
                                id(result.snapshot["tuple"]))
            self.assertNotEqual(id(value.list),
                                id(result.snapshot["list"]))
            self.assertNotEqual(id(value.set),
                                id(result.snapshot["set"]))
            self.assertNotEqual(id(value.dict),
                                id(result.snapshot["dict"]))


        serializer = self.serializer
        obj = BasicSerializableDummy()

        check(obj, serializer.pack_serializable(obj))
        check(obj, serializer.pack_value(obj))
        check(obj, serializer.serialize(obj))


class TestSExpSerializer(BaseSerializerTest):

    def setUp(self):
        self.serializer = serialization.SExpSerializer()

    def testBasicImmutablePacking(self):
        self.checkPackingValue("pack_str", "dummy", "dummy")
        self.checkPackingValue("pack_int", 42, 42)
        self.checkPackingValue("pack_long", 2**66, 2**66)
        self.checkPackingAlmostValue("pack_float", 3.1415926, 3.1415926)

        self.checkPackingValue("pack_unicode", u"dummy", ["unicode", "dummy"])
        self.checkPackingValue("pack_unicode", u"áéí",
                               ["unicode", '\xc3\xa1\xc3\xa9\xc3\xad'])
        self.checkPackingValue("pack_bool", True, ["boolean", "true"])
        self.checkPackingValue("pack_none", None, ["None"])

        self.checkPackingType("pack_str", "dummy", str)
        self.checkPackingType("pack_int", 42, int)
        self.checkPackingType("pack_long", 2**66, long)
        self.checkPackingType("pack_float", 3.1415926, float)

    def testBasicMutablePacking(self):
        self.checkPackingValue("pack_tuple", (), ["tuple"])
        self.checkPackingValue("pack_tuple", (1, 2, 3), ["tuple", 1, 2, 3])
        self.checkPackingValue("pack_list", [], ["list"])
        self.checkPackingValue("pack_list", [1, 2, 3], ["list", 1, 2, 3])
        self.checkPackingValue("pack_set", set([]), ["set"])
        self.checkPackingValue("pack_set", set([1, 3]), ["set", 1, 3])
        self.checkPackingValue("pack_dict", {}, ["dictionary"])
        self.checkPackingValue("pack_dict", {1: 2, 3: 4},
                               ["dictionary", [1, 2], [3, 4]])

    def testJellyCompatibility(self):

        def check(value):
            result1 = self.serializer.serialize(value)
            result2 = jelly.jelly(value)
            self.assertEqual(result1, result2)

        # Simple test without references
        value = ["a", u"b", 2**66, True, False, None,
                 BasicSerializableDummy(),
                 (1, (2, 3), [4, 5], set([6, 7]), {8: 9}),
                 [1, (2, 3), [4, 5], set([6, 7]), {8: 9}],
                 set([1, (2, 3)]),
                 {1: (2, 3), 4: [5, 6], 7: set([8, 9]),
                  10: {11: 12}, (13, 14): 15}]

        check(value)
