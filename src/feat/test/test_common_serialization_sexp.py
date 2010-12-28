# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import itertools
import types

from twisted.spread import jelly

from feat.common import reflect, serialization
from feat.common.serialization import sexp
from feat.interface.serialization import *

from . import common_serialization


@serialization.register
class Dummy(serialization.Serializable):
    pass


class ListSerializableDummy(serialization.Serializable, jelly.Jellyable):

    def __init__(self, values):
        self.values = list(values)

    def recover(self, snapshot):
        self.values = list(snapshot)

    def snapshot(self):
        return list(self.values)

    def getStateFor(self, jellyer):
        return self.snapshot()

    def __eq__(self, value):
        return self.values == value.values


class SExpConvertersTest(common_serialization.ConverterTest):

    def setUp(self):
        self.serializer = sexp.Serializer()
        self.unserializer = sexp.Unserializer()

    def testJellyUnjelly(self):
        # jelly do not support meta types and enums
        caps = set(self.serializer.capabilities)
        caps -= set([Capabilities.meta_types,
                     Capabilities.enum_values,
                     Capabilities.enum_keys])
        self.checkSymmetry(jelly.jelly, jelly.unjelly, capabilities=caps)

    def testUnjellyCompatibility(self):
        # jelly do not support meta types and enums
        caps = set(self.serializer.capabilities)
        caps -= set([Capabilities.meta_types,
                     Capabilities.enum_values,
                     Capabilities.enum_keys])
        self.checkSymmetry(self.serializer.convert, jelly.unjelly,
                           capabilities=caps)

    def testJellyCompatibility(self):
        # jelly do not support meta types
        caps = set(self.serializer.capabilities)
        caps -= set([Capabilities.meta_types,
                     Capabilities.enum_values,
                     Capabilities.enum_keys])
        self.checkSymmetry(jelly.jelly, self.unserializer.convert,
                           capabilities=caps)

    def testInstancesSerialization(self):
        # Because dictionaries item order is not guaranteed we cannot
        # compare directly directlly the result
        obj = common_serialization.SerializableDummy()
        name = reflect.canonical_name(common_serialization.SerializableDummy)
        data = self.serialize(obj)
        self.assertTrue(isinstance(data, list))
        self.assertEqual(data[0], name)
        self.assertTrue(isinstance(data[1], list))
        self.assertEqual(data[1][0], "dictionary")
        dict_vals = data[1][1:]
        self.assertEqual(len(dict_vals), 12)
        self.assertTrue(['none', ['None']] in dict_vals)
        self.assertTrue(['set', ['set', 1, 2, 3]] in dict_vals)
        self.assertTrue(['str', 'dummy'] in dict_vals)
        self.assertTrue(['tuple', ['tuple', 1, 2, 3]] in dict_vals)
        self.assertTrue(['int', 42] in dict_vals)
        self.assertTrue(['float', 3.1415926] in dict_vals)
        self.assertTrue(['list', ['list', 1, 2, 3]] in dict_vals)
        self.assertTrue(['long', 2**66] in dict_vals)
        self.assertTrue(['bool', ['boolean', 'true']] in dict_vals)
        self.assertTrue(['unicode', ['unicode', 'dummy']] in dict_vals)
        self.assertTrue(['dict', ['dictionary', [1, 2], [3, 4]]] in dict_vals)
        self.assertTrue(['ref', ['None']] in dict_vals)

        obj = ListSerializableDummy([1, 2, 3])
        name = reflect.canonical_name(ListSerializableDummy)
        self.assertEqual(self.serialize(obj),
                         [name, ['list', 1, 2, 3]])

    def convertion_table(self, capabilities):
        ### Basic immutable types ###
        yield str, [""], str, [""], False
        yield str, ["dummy"], str, ["dummy"], False
        yield unicode, [u""], list, [["unicode", ""]], True
        yield unicode, [u"dummy"], list, [["unicode", "dummy"]], True
        yield (unicode, [u"áéí"], list,
               [["unicode", '\xc3\xa1\xc3\xa9\xc3\xad']], True)
        yield int, [0], int, [0], False
        yield int, [42], int, [42], False
        yield int, [-42], int, [-42], False
        yield long, [0L], long, [0L], False
        yield long, [2**66], long, [2**66], False
        yield long, [-2**66], long, [-2**66], False
        yield float, [0.0], float, [0.0], False
        yield float, [3.1415926], float, [3.1415926], False
        yield float, [1e24], float, [1e24], False
        yield float, [1e-24], float, [1e-24], False
        yield bool, [True], list, [["boolean", "true"]], True
        yield bool, [False], list, [["boolean", "false"]], True
        yield types.NoneType, [None], list, [["None"]], True

        ### Types ###
        from datetime import datetime
        yield type, [int], list, [["class", "__builtin__.int"]], False
        yield type, [datetime], list, [["class", "datetime.datetime"]], False
        name = reflect.canonical_name(common_serialization.SerializableDummy)
        yield (type, [common_serialization.SerializableDummy],
               list, [["class", name]], False)

        ### Enums ###

        DummyEnum = common_serialization.DummyEnum
        name = reflect.canonical_name(DummyEnum)

        if Capabilities.enum_values in Capabilities:
            yield (DummyEnum, [DummyEnum.a],
                   list, [["enum", name, int(DummyEnum.a)]], False)
            yield (DummyEnum, [DummyEnum.c],
                   list, [["enum", name, int(DummyEnum.c)]], False)

        ### Basic containers ###
        yield tuple, [()], list, [["tuple"]], False # Exception for empty tuple
        yield tuple, [(1, 2, 3)], list, [["tuple", 1, 2, 3]], True
        yield list, [[]], list, [["list"]], True
        yield list, [[1, 2, 3]], list, [["list", 1, 2, 3]], True
        yield set, [set([])], list, [["set"]], True
        yield set, [set([1, 3])], list, [["set", 1, 3]], True
        yield dict, [{}], list, [["dictionary"]], True
        yield (dict, [{1: 2, 3: 4}], list,
               [["dictionary", [1, 2], [3, 4]]], True)

        # Tuple with various value type
        yield (tuple, [(0.1, 2**45, "a", u"z", False, None,
                        (1, ), [2], set([3]), {4: 5})],
               list, [["tuple", 0.1, 2**45, "a", ["unicode", "z"],
                       ["boolean", "false"], ["None"], ["tuple", 1],
                       ["list", 2], ["set", 3], ["dictionary", [4, 5]]]], True)
        # List with various value type
        yield (list, [[0.1, 2**45, "a", u"z", False, None,
                        (1, ), [2], set([3]), {4: 5}]],
               list, [["list", 0.1, 2**45, "a", ["unicode", "z"],
                       ["boolean", "false"], ["None"], ["tuple", 1],
                       ["list", 2], ["set", 3], ["dictionary", [4, 5]]]], True)
        # Set with various value type
        # Because set are not ordered every order is possible
        values = [0.1, 2**45, "a", ["unicode", "z"],
                  ["boolean", "false"], ["None"], ["tuple", 1]]
        expected = [["set"] + values]
        alternatives = [["set"] + list(perm)
                        for perm in itertools.permutations(values)]
        yield (set, [set([0.1, 2**45, "a", u"z", False, None, (1, )])], [],
               list, expected, alternatives, True)
        # Dictionary with various value type
        # Because dictionaries are not ordered every order is possible
        values = [[1, 0.1], [2, 2**45], [3, "a"], [4, ["unicode", "z"]],
                  [5, ["boolean", "false"]]]
        expected = [["dictionary"] + values]
        alternatives = [["dictionary"] + list(perm)
                        for perm in itertools.permutations(values)]
        yield (dict, [{1: 0.1, 2: 2**45, 3: "a", 4: u"z", 5: False}], [],
               list, expected, alternatives, True)

        values = [[6, ["None"]], [7, ["tuple", 1]], [8, ["list", 2]],
                  [9, ["set", 3]], [0, ["dictionary", [4, 5]]]]
        expected = [["dictionary"] + values]
        alternatives = [["dictionary"] + list(perm)
                        for perm in itertools.permutations(values)]
        yield (dict, [{6: None, 7: (1, ), 8: [2], 9: set([3]), 0: {4: 5}}], [],
               list, expected, alternatives, True)

        values = [[0.1, 1], [2**45, 2], ["a", 3], [["unicode", "z"], 4],
                  [["boolean", "false"], 5], [["None"], 6], [["tuple", 1], 7]]
        expected = [["dictionary"] + values]
        alternatives = [["dictionary"] + list(perm)
                        for perm in itertools.permutations(values)]
        yield (dict, [{0.1: 1, 2**45: 2, "a": 3, u"z": 4,
                       False: 5, None: 6, (1, ): 7}], [],
               list, expected, alternatives, True)

        ### References and Dereferences ###


        Ref = lambda refid, value: ["reference", refid, value]
        Deref = lambda refid: ["dereference", refid]

        # Simple reference in list
        a = []
        b = [a, a]
        yield list, [b], list, [["list", Ref(1, ["list"]), Deref(1)]], True

        # Simple reference in tuple
        a = ()
        b = (a, a)
        yield tuple, [b], list, [["tuple", Ref(1, ["tuple"]), Deref(1)]], True

        # Simple dereference in dict value.
        a = {}
        b = [a, {1: a}]
        yield (list, [b], list, [["list", Ref(1, ["dictionary"]),
                                 ["dictionary", [1, Deref(1)]]]], True)

        # Simple reference in dict value.
        a = set([])
        b = [{1: a}, a]
        yield (list, [b], list, [["list",
                                  ["dictionary", [1, Ref(1, ["set"])]],
                                  Deref(1)]], True)

        # Simple dereference in dict keys.
        a = ()
        b = [a, {a: 1}]
        yield (list, [b], list, [["list", Ref(1, ["tuple"]),
                                 ["dictionary", [Deref(1), 1]]]], True)

        # Simple reference in dict keys.
        a = (1, 2)
        b = [{a: 1}, a]
        yield (list, [b], list, [["list",
                                  ["dictionary", [Ref(1, ["tuple", 1, 2]), 1]],
                                  Deref(1)]], True)

        # Multiple reference in dictionary values, because dictionary order
        # is not predictable all possibilities have to be tested
        a = set()
        b = {1: a, 2: a, 3: a}

        values1 = [[1, Ref(1, ["set"])], [2, Deref(1)], [3, Deref(1)]]
        values2 = [[2, Ref(1, ["set"])], [3, Deref(1)], [1, Deref(1)]]
        values3 = [[3, Ref(1, ["set"])], [1, Deref(1)], [2, Deref(1)]]
        expected1 = [["dictionary"] + values1]
        expected2 = [["dictionary"] + values2]
        expected3 = [["dictionary"] + values3]
        alternatives1 = [["dictionary"] + list(perm)
                         for perm in itertools.permutations(values1)]
        alternatives2 = [["dictionary"] + list(perm)
                         for perm in itertools.permutations(values2)]
        alternatives3 = [["dictionary"] + list(perm)
                         for perm in itertools.permutations(values3)]

        yield (dict, [b], [], list, expected1 + expected2 + expected3,
               alternatives1 + alternatives2 + alternatives3, True)

        # Multiple reference in dictionary keys, because dictionary order
        # is not predictable all possibilities have to be tested
        a = (1, )
        b = {(1, a): 1, (2, a): 2, (3, a): 3}

        values1 = [[["tuple", 1, Ref(1, ["tuple", 1])], 1],
                   [["tuple", 2, Deref(1)], 2], [["tuple", 3, Deref(1)], 3]]
        values2 = [[["tuple", 2, Ref(1, ["tuple", 1])], 2],
                   [["tuple", 3, Deref(1)], 3], [["tuple", 1, Deref(1)], 1]]
        values3 = [[["tuple", 3, Ref(1, ["tuple", 1])], 3],
                   [["tuple", 1, Deref(1)], 1], [["tuple", 2, Deref(1)], 2]]
        expected1 = [["dictionary"] + values1]
        expected2 = [["dictionary"] + values2]
        expected3 = [["dictionary"] + values3]
        alternatives1 = [["dictionary"] + list(perm)
                         for perm in itertools.permutations(values1)]
        alternatives2 = [["dictionary"] + list(perm)
                         for perm in itertools.permutations(values2)]
        alternatives3 = [["dictionary"] + list(perm)
                         for perm in itertools.permutations(values3)]

        yield (dict, [b], [], list, expected1 + expected2 + expected3,
               alternatives1 + alternatives2 + alternatives3, True)

        # Simple dereference in set.
        a = ("a", )
        b = [a, set([a])]
        yield (list, [b], list, [["list", Ref(1, ["tuple", "a"]),
                                  ["set", Deref(1)]]], True)

        # Simple reference in set.
        a = ("b", )
        b = [set([a]), a]
        yield (list, [b], list, [["list", ["set", Ref(1, ["tuple", "b"])],
                                  Deref(1)]], True)

        # Multiple reference in set, because set values order
        # is not predictable all possibilities have to be tested
        a = (1, )
        b = set([(1, a), (2, a), (3, a)])

        values1 = [["tuple", 1, Ref(1, ["tuple", 1])],
                   ["tuple", 2, Deref(1)], ["tuple", 3, Deref(1)]]
        values2 = [["tuple", 2, Ref(1, ["tuple", 1])],
                   ["tuple", 3, Deref(1)], ["tuple", 1, Deref(1)]]
        values3 = [["tuple", 3, Ref(1, ["tuple", 1])],
                   ["tuple", 1, Deref(1)], ["tuple", 2, Deref(1)]]
        expected1 = [["set"] + values1]
        expected2 = [["set"] + values2]
        expected3 = [["set"] + values3]
        alternatives1 = [["set"] + list(perm)
                         for perm in itertools.permutations(values1)]
        alternatives2 = [["set"] + list(perm)
                         for perm in itertools.permutations(values2)]
        alternatives3 = [["set"] + list(perm)
                         for perm in itertools.permutations(values3)]

        yield (set, [b], [], list, expected1 + expected2 + expected3,
               alternatives1 + alternatives2 + alternatives3, True)

        # List self-reference
        a = []
        a.append(a)
        yield list, [a], list, [Ref(1, ["list", Deref(1)])], True

        # Dict self-reference
        a = {}
        a[1] = a
        yield dict, [a], list, [Ref(1, ["dictionary", [1, Deref(1)]])], True

        # Multiple references
        a = []
        b = [a]
        c = [a, b]
        d = [a, b, c]
        yield (list, [d], list, [["list", Ref(1, ["list"]),
                                  Ref(2, ["list", Deref(1)]),
                                 ["list", Deref(1), Deref(2)]]], True)

        # Complex structure without dict or set
        a = ()
        b = (a, )
        b2 = set(b)
        c = (a, b)
        c2 = [c]
        d = (a, b, c)
        d2 = [a, b2, c2]
        e = (b, c, d)
        e2 = [b2, c2, e]
        g = (b, b2, c, c2, d, d2, e, e2)

        yield (tuple, [g], list,
               [['tuple', Ref(2, ['tuple', Ref(1, ['tuple'])]),
                 Ref(4, ['set', Deref(1)]),
                 Ref(3, ['tuple', Deref(1), Deref(2)]),
                 Ref(5, ['list', Deref(3)]),
                 Ref(6, ['tuple', Deref(1), Deref(2), Deref(3)]),
                 ['list', Deref(1), Deref(4), Deref(5)],
                 Ref(7, ['tuple', Deref(2), Deref(3), Deref(6)]),
                 ['list', Deref(4), Deref(5), Deref(7)]]], True)

        Klass = common_serialization.SerializableDummy

        # Object instances
        o = Klass()
        # Update the instance to have only one attribute
        del o.set
        del o.dict
        del o.str
        del o.unicode
        del o.long
        del o.float
        del o.bool
        del o.none
        del o.list
        del o.tuple
        del o.ref
        o.int = 101
        yield (Klass, [o], list,
               [[reflect.canonical_name(Klass),
                 ["dictionary", ["int", 101]]]], True)

        Klass = Dummy
        name = reflect.canonical_name(Klass)
        Inst = lambda v: [name, v]

        a = Klass()
        b = Klass()
        c = Klass()

        a.ref = b
        b.ref = a
        c.ref = c

        yield (Klass, [a], list,
               [Ref(1, Inst(["dictionary",
                    ["ref", Inst(["dictionary", ["ref", Deref(1)]])]]))], True)

        yield (Klass, [b], list,
               [Ref(1, Inst(["dictionary",
                    ["ref", Inst(["dictionary", ["ref", Deref(1)]])]]))], True)

        yield (Klass, [c], list,
               [Ref(1, Inst(["dictionary", ["ref", Deref(1)]]))], True)

        yield (list, [[a, b]], list,
               [["list", Ref(1, Inst(["dictionary", ["ref",
                    Ref(2, Inst(["dictionary",
                                 ["ref", Deref(1)]]))]])), Deref(2)]], True)

        yield (list, [[a, c]], list,
               [["list", Ref(1, Inst(["dictionary", ["ref",
                    Inst(["dictionary", ["ref", Deref(1)]])]])),
                    Ref(2, Inst(["dictionary", ["ref", Deref(2)]]))]], True)
