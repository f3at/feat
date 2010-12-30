# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import itertools
import types

from feat.common import reflect, serialization
from feat.common.serialization import base, json
from feat.interface.serialization import *

from . import common_serialization


@serialization.register
class DummyClass(serialization.Serializable):

    def dummy_method(self):
        pass


def dummy_function():
    pass


class JSONConvertersTest(common_serialization.ConverterTest):

    def setUp(self):
        common_serialization.ConverterTest.setUp(self)
        ext = self.externalizer
        self.serializer = json.Serializer(externalizer=ext)
        self.unserializer = json.Unserializer(externalizer=ext)

    def convertion_table(self, capabilities, freezing):
        ### Basic immutable types ###

        yield str, [""], str, ['["_enc", "UTF8", ""]',
                               '["_bytes", ""]'], False
        yield str, ["dummy"], str, ['["_enc", "UTF8", "dummy"]',
                                    '["_bytes", "ZHVtbXk="]'], False
        yield str, ["\xFF"], str, ['["_bytes", "/w=="]'], False
        yield unicode, [u""], str, ['""'], False
        yield unicode, [u"dummy"], str, ['"dummy"'], False
        yield unicode, [u"áéí"], str, ['"\\u00e1\\u00e9\\u00ed"'], False
        yield int, [0], str, ["0"], False
        yield int, [42], str, ["42"], False
        yield int, [-42], str, ["-42"], False
        yield float, [0.0], str, ["0.0"], False
        yield float, [3.141], str, ["3.141"], False
        yield float, [-3.141], str, ["-3.141"], False
        yield float, [1e20], str, ["1e+20"], False
        yield float, [1e-22], str, ["1e-22"], False
        yield bool, [True], str, ["true"], False
        yield bool, [False], str, ["false"], False
        yield type(None), [None], str, ["null"], False

        ### Types ###
        from datetime import datetime
        yield type, [int], str, ['["_type", "__builtin__.int"]'], False
        yield (type, [datetime],
               str, ['["_type", "datetime.datetime"]'], False)
        yield (type, [common_serialization.SerializableDummy],
               str, ['["_type", "feat.test.common_serialization.'
                     'SerializableDummy"]'], False)

        ### Enums ###

        DummyEnum = common_serialization.DummyEnum

        yield (DummyEnum, [DummyEnum.a],
               str, ['["_enum", "feat.test.common_serialization.'
                     'DummyEnum.a"]'], False)
        yield (DummyEnum, [DummyEnum.c],
               str, ['["_enum", "feat.test.common_serialization.'
                     'DummyEnum.c"]'], False)

        ### External References ###

        if not freezing:
            name = '["_enc", "UTF8", "%s"]' % self.ext_val.type_name
            identifier = '["_tuple", %s, %d]' % (name, id(self.ext_val))
            yield (common_serialization.SerializableDummy, [self.ext_val],
                   str, ['["_ext", %s]' % identifier], False)

        ### Freezing-Only Types ###

        if freezing:
            mod_name = "feat.test.test_common_serialization_json"
            fun_name = '"%s.dummy_function"' % mod_name
            meth_name = '"%s.DummyClass.dummy_method"' % mod_name

            yield types.FunctionType, [dummy_function], str, [fun_name], True

            yield (types.FunctionType, [DummyClass.dummy_method],
                   str, [meth_name], True)

            o = DummyClass()
            yield types.FunctionType, [o.dummy_method], str, [meth_name], True

        #### Basic mutable types plus tuples ###

        # Exception for empty tuple singleton
        yield tuple, [()], str, ['["_tuple"]'], False
        yield tuple, [(1, 2, 3)], str, ['["_tuple", 1, 2, 3]'], True
        yield list, [[]], str, ['[]'], True
        yield list, [[1, 2, 3]], str, ['[1, 2, 3]'], True
        yield set, [set([])], str, ['["_set"]'], True
        yield set, [set([1, 3])], str, ['["_set", 1, 3]'], True
        yield dict, [{}], str, ['{}'], True
        yield dict, [{"1": 2, "3": 4}], str, ['{"1": 2, "3": 4}'], True

        # Container with different types
        yield (tuple, [(0.11, "a", u"z", False, None,
                        (1, ), [2], set([3]), {"4": 5})],
               str, ['["_tuple", 0.11, ["_enc", "UTF8", "a"], "z", false, '
                     'null, ["_tuple", 1], [2], ["_set", 3], {"4": 5}]'], True)
        yield (list, [[0.11, "a", u"z", False, None,
                       (1, ), [2], set([3]), {"4": 5}]],
               str, ['[0.11, ["_enc", "UTF8", "a"], "z", false, null, '
                     '["_tuple", 1], [2], ["_set", 3], {"4": 5}]'], True)

        ### References and Dereferences ###

        # Simple reference in list
        a = []
        b = [a, a]
        yield list, [b], str, ['[["_ref", 1, []], ["_deref", 1]]'], True

        # Simple reference in tuple
        a = ()
        b = (a, a)
        yield tuple, [b], str, ['["_tuple", ["_ref", 1, ["_tuple"]], '
                                '["_deref", 1]]'], True

        # Simple dereference in dict value.
        a = []
        b = [a, {"1": a}]
        yield list, [b], str, ['[["_ref", 1, []], {"1": ["_deref", 1]}]'], True

        # Simple reference in dict value.
        a = []
        b = [{"1": a}, a]
        yield list, [b], str, ['[{"1": ["_ref", 1, []]}, ["_deref", 1]]'], True

        # Multiple reference in dictionary values, because dictionary order
        # is not predictable all possibilities have to be tested
        a = {}
        b = {"1": a, "2": a, "3": a}
        yield (dict, [b], str,
            ['{"1": ["_ref", 1, {}], "2": ["_deref", 1], "3": ["_deref", 1]}',
             '{"1": ["_ref", 1, {}], "3": ["_deref", 1], "2": ["_deref", 1]}',
             '{"2": ["_ref", 1, {}], "1": ["_deref", 1], "3": ["_deref", 1]}',
             '{"2": ["_ref", 1, {}], "3": ["_deref", 1], "1": ["_deref", 1]}',
             '{"3": ["_ref", 1, {}], "1": ["_deref", 1], "2": ["_deref", 1]}',
             '{"3": ["_ref", 1, {}], "2": ["_deref", 1], "1": ["_deref", 1]}'],
               True)

        # Simple dereference in set.
        a = ()
        b = [a, set([a])]
        yield list, [b], str, ['[["_ref", 1, ["_tuple"]], '
                               '["_set", ["_deref", 1]]]'], True

        # Simple reference in set.
        a = ()
        b = [set([a]), a]
        yield list, [b], str, ['[["_set", ["_ref", 1, ["_tuple"]]], '
                               '["_deref", 1]]'], True

        # Multiple reference in set, because set values order
        # is not predictable all possibilities have to be tested
        a = ()
        b = set([(1, a), (2, a)])
        yield (set, [b], str,
               ['["_set", ["_tuple", 1, ["_ref", 1, ["_tuple"]]], '
                '["_tuple", 2, ["_deref", 1]]]',
                '["_set", ["_tuple", 2, ["_ref", 1, ["_tuple"]]], '
                '["_tuple", 1, ["_deref", 1]]]'], True)

        # List self-reference
        a = []
        a.append(a)
        yield list, [a], str, ['["_ref", 1, [["_deref", 1]]]'], True

        # Dict self-reference
        a = {}
        a["1"] = a
        yield dict, [a], str, ['["_ref", 1, {"1": ["_deref", 1]}]'], True

        # Multiple references
        a = []
        b = [a]
        c = [a, b]
        d = [a, b, c]
        yield list, [d], str, ['[["_ref", 1, []], '
                               '["_ref", 2, [["_deref", 1]]], '
                               '[["_deref", 1], ["_deref", 2]]]'], True

        # Default instance
        o = DummyClass()
        o.value = 42

        if freezing:
            yield (DummyClass, [o], str, ['{"value": 42}'], True)
        else:
            name = reflect.canonical_name(o)
            yield (DummyClass, [o], str,
                   ['{"_type": "%s", "value": 42}' % name,
                    '{"value": 42, "_type": "%s"}' % name], True)

        Klass = DummyClass
        name = reflect.canonical_name(Klass)

        a = Klass()
        b = Klass()
        c = Klass()

        a.ref = b
        b.ref = a
        c.ref = c

        if freezing:
            yield (Klass, [a], str,
                   ['["_ref", 1, {"ref": {"ref": ["_deref", 1]}}]'], True)
            yield (Klass, [b], str,
                   ['["_ref", 1, {"ref": {"ref": ["_deref", 1]}}]'], True)
            yield (Klass, [c], str,
                   ['["_ref", 1, {"ref": ["_deref", 1]}]'], True)

        else:
            yield (Klass, [a], str,
                   [('["_ref", 1, {"_type": "%s", "ref": {"_type": "%s", '
                     '"ref": ["_deref", 1]}}]') % (name, name)], True)
            yield (Klass, [b], str,
                   [('["_ref", 1, {"_type": "%s", "ref": {"_type": "%s", '
                     '"ref": ["_deref", 1]}}]') % (name, name)], True)
            yield (Klass, [c], str, [('["_ref", 1, {"_type": "%s", "ref": '
                                      '["_deref", 1]}]') % (name, )], True)
