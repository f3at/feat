# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import types

from feat.common import serialization, reflect
from feat.common.serialization import pytree
from feat.interface.serialization import *

from . import common_serialization


@serialization.register
class DummyClass(serialization.Serializable):

    def dummy_method(self):
        pass


def dummy_function():
        pass


class PyTreeConvertersTest(common_serialization.ConverterTest):

    def setUp(self):
        self.serializer = pytree.Serializer()
        self.unserializer = pytree.Unserializer()

    def convertion_table(self, capabilities, freezing):
        ### Basic immutable types ###

        yield str, [""], str, [""], False
        yield str, ["dummy"], str, ["dummy"], False
        yield unicode, [u""], unicode, [u""], False
        yield unicode, [u"dummy"], unicode, [u"dummy"], False
        yield unicode, [u"áéí"], unicode, [u"áéí"], False
        yield int, [0], int, [0], False
        yield int, [42], int, [42], False
        yield int, [-42], int, [-42], False
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
        yield bool, [True], bool, [True], False
        yield bool, [False], bool, [False], False
        yield type(None), [None], type(None), [None], False

        ### Types ###
        from datetime import datetime
        yield type, [int], type, [int], False
        yield type, [datetime], type, [datetime], False
        yield (type, [common_serialization.SerializableDummy],
               type, [common_serialization.SerializableDummy], False)

        ### Enums ###

        DummyEnum = common_serialization.DummyEnum

        yield DummyEnum, [DummyEnum.a], DummyEnum, [DummyEnum.a], False
        yield DummyEnum, [DummyEnum.c], DummyEnum, [DummyEnum.c], False

        ### Freezing-Only Types ###

        if freezing:
            mod_name = "feat.test.test_common_serialization_pytree"
            fun_name = mod_name + ".dummy_function"
            meth_name = mod_name + ".DummyClass.dummy_method"

            yield types.FunctionType, [dummy_function], str, [fun_name], True

            yield (types.FunctionType, [DummyClass.dummy_method],
                   str, [meth_name], True)

            o = DummyClass()
            yield types.FunctionType, [o.dummy_method], str, [meth_name], True

        #### Basic mutable types plus tuples ###

        # Exception for empty tuple singleton
        yield tuple, [()], tuple, [()], False
        yield tuple, [(1, 2, 3)], tuple, [(1, 2, 3)], True
        yield list, [[]], list, [[]], True
        yield list, [[1, 2, 3]], list, [[1, 2, 3]], True
        yield set, [set([])], set, [set([])], True
        yield set, [set([1, 3])], set, [set([1, 3])], True
        yield dict, [{}], dict, [{}], True
        yield dict, [{1: 2, 3: 4}], dict, [{1: 2, 3: 4}], True

        # Container with different types
        yield (tuple, [(0.1, 2**45, "a", u"z", False, None,
                        (1, ), [2], set([3]), {4: 5})],
               tuple, [(0.1, 2**45, "a", u"z", False, None,
                        (1, ), [2], set([3]), {4: 5})], True)
        yield (list, [[0.1, 2**45, "a", u"z", False, None,
                       (1, ), [2], set([3]), {4: 5}]],
               list, [[0.1, 2**45, "a", u"z", False, None,
                       (1, ), [2], set([3]), {4: 5}]], True)
        yield (set, [set([0.1, 2**45, "a", u"z", False, None, (1)])],
               set, [set([0.1, 2**45, "a", u"z", False, None, (1)])], True)
        yield (dict, [{0.2: 0.1, 2**42: 2**45, "x": "a", u"y": u"z",
                       True: False, None: None, (-1, ): (1, ),
                       8: [2], 9: set([3]), 10: {4: 5}}],
               dict, [{0.2: 0.1, 2**42: 2**45, "x": "a", u"y": u"z",
                       True: False, None: None, (-1, ): (1, ),
                       8: [2], 9: set([3]), 10: {4: 5}}], True)

        ### References and Dereferences ###

        Ref = pytree.Reference
        Deref = pytree.Dereference

        # Simple reference in list
        a = []
        b = [a, a]
        yield list, [b], list, [[Ref(1, []), Deref(1)]], True

        # Simple reference in tuple
        a = ()
        b = (a, a)
        yield tuple, [b], tuple, [(Ref(1, ()), Deref(1))], True

        # Simple dereference in dict value.
        a = ()
        b = [a, {1: a}]
        yield list, [b], list, [[Ref(1, ()), {1: Deref(1)}]], True

        # Simple reference in dict value.
        a = ()
        b = [{1: a}, a]
        yield list, [b], list, [[{1: Ref(1, ())}, Deref(1)]], True

        # Simple dereference in dict keys.
        a = ()
        b = [a, {a: 1}]
        yield list, [b], list, [[Ref(1, ()), {Deref(1): 1}]], True

        # Simple reference in dict keys.
        a = ()
        b = [{a: 1}, a]
        yield list, [b], list, [[{Ref(1, ()): 1}, Deref(1)]], True

        # Multiple reference in dictionary values, because dictionary order
        # is not predictable all possibilities have to be tested
        a = {}
        b = {1: a, 2: a, 3: a}
        yield (dict, [b], dict,
               [{1: Ref(1, {}), 2: Deref(1), 3: Deref(1)},
                {1: Deref(1), 2: Ref(1, {}), 3: Deref(1)},
                {1: Deref(1), 2: Deref(1), 3: Ref(1, {})}],
               True)

        # Multiple reference in dictionary keys, because dictionary order
        # is not predictable all possibilities have to be tested
        a = (1, )
        b = {(1, a): 1, (2, a): 2, (3, a): 3}
        yield (dict, [b], dict,
               [{(1, Ref(1, (1, ))): 1, (2, Deref(1)): 2, (3, Deref(1)): 3},
                {(1, Deref(1)): 1, (2, Ref(1, (1, ))): 2, (3, Deref(1)): 3},
                {(1, Deref(1)): 1, (2, Deref(1)): 2, (3, Ref(1, (1, ))): 3}],
               True)

        # Simple dereference in set.
        a = ()
        b = [a, set([a])]
        yield list, [b], list, [[Ref(1, ()), set([Deref(1)])]], True

        # Simple reference in set.
        a = ()
        b = [set([a]), a]
        yield list, [b], list, [[set([Ref(1, ())]), Deref(1)]], True

        # Multiple reference in set, because set values order
        # is not predictable all possibilities have to be tested
        a = (1, )
        b = set([(1, a), (2, a), (3, a)])
        yield (set, [b], set,
               [set([(1, Ref(1, (1, ))), (2, Deref(1)), (3, Deref(1))]),
                set([(1, Deref(1)), (2, Ref(1, (1, ))), (3, Deref(1))]),
                set([(1, Deref(1)), (2, Deref(1)), (3, Ref(1, (1, )))])],
               True)

        # List self-reference
        a = []
        a.append(a)
        yield list, [a], Ref, [Ref(1, [Deref(1)])], True

        # Dict self-reference
        a = {}
        a[1] = a
        yield dict, [a], Ref, [Ref(1, {1: Deref(1)})], True

        # Multiple references
        a = []
        b = [a]
        c = [a, b]
        d = [a, b, c]
        yield (list, [d], list, [[Ref(1, []), Ref(2, [Deref(1)]),
                                 [Deref(1), Deref(2)]]], True)

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

        yield (tuple, [g], tuple, [(Ref(2, (Ref(1, ()), )),
                                    Ref(4, set([Deref(1)])),
                                    Ref(3, (Deref(1), Deref(2))),
                                    Ref(5, [Deref(3)]),
                                    Ref(6, (Deref(1), Deref(2), Deref(3))),
                                    [Deref(1), Deref(4), Deref(5)],
                                    Ref(7, (Deref(2), Deref(3), Deref(6))),
                                    [Deref(4), Deref(5), Deref(7)])], True)

        Klass = common_serialization.SerializableDummy
        name = reflect.canonical_name(Klass)

        if freezing:
            Inst = lambda v: v
            InstType = dict
        else:
            Inst = lambda v: pytree.Instance(name, v)
            InstType = pytree.Instance

        # Default instance
        o = Klass()
        yield (Klass, [o], InstType,
               [Inst({"str": "dummy",
                      "unicode": u"dummy",
                      "int": 42,
                      "long": 2**66,
                      "float": 3.1415926,
                      "bool": True,
                      "none": None,
                      "list": [1, 2, 3],
                      "tuple": (1, 2, 3),
                      "set": set([1, 2, 3]),
                      "dict": {1: 2, 3: 4},
                      "ref": None})], True)

        Klass = DummyClass
        name = reflect.canonical_name(Klass)

        if freezing:
            Inst = lambda v: v
            InstType = dict
        else:
            Inst = lambda v: pytree.Instance(name, v)
            InstType = pytree.Instance

        a = Klass()
        b = Klass()
        c = Klass()

        a.ref = b
        b.ref = a
        c.ref = c

        yield (Klass, [a], Ref,
               [Ref(1, Inst({"ref":
                    Inst({"ref": Deref(1)})}))], True)

        yield (Klass, [b], Ref,
               [Ref(1, Inst({"ref":
                    Inst({"ref": Deref(1)})}))], True)

        yield (Klass, [c], Ref,
               [Ref(1, Inst({"ref": Deref(1)}))], True)

        yield (list, [[a, b]], list,
               [[Ref(1, Inst({"ref":
                    Ref(2, Inst({"ref": Deref(1)}))})), Deref(2)]], True)

        yield (list, [[a, c]], list,
               [[Ref(1, Inst({"ref":
                    Inst({"ref": Deref(1)})})),
                    Ref(2, Inst({"ref": Deref(2)}))]], True)

        yield (list, [[a, [a, [a, [a]]]]], list,
               [[Ref(1, Inst({'ref': Inst({'ref': Deref(1)})})),
                 [Deref(1), [Deref(1), [Deref(1)]]]]], True)

        yield (tuple, [(a, (a, (a, (a, ))))], tuple,
               [(Ref(1, Inst({'ref': Inst({'ref': Deref(1)})})),
                 (Deref(1), (Deref(1), (Deref(1), ))))], True)
