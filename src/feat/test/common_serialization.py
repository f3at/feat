# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import types

from twisted.python.reflect import qual
from twisted.spread import jelly
from twisted.trial.unittest import SkipTest

from feat.common import serialization
from feat.interface.serialization import *

from . import common


@serialization.register
class SerializableDummy(serialization.Serializable, jelly.Jellyable):
    '''Simple dummy class that implements various serialization scheme.'''

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
        self.ref = None

    def getStateFor(self, jellyer):
        return self.snapshot()

    def unjellyFor(self, unjellyer, data):
        # The way to handle circular references in spread
        unjellyer.unjellyInto(self, "__dict__", data[1])
        return self

    def __setitem__(self, name, value):
        # Needed by twisted spread to handle circular references
        setattr(self, name, value)

    def __repr__(self):
        return "<%s: %s>" % (type(self).__name__, repr(self.__dict__))

    def __eq__(self, value):
        return (value is self
                or (self.str == value.str
                    and self.unicode == value.unicode
                    and self.int == value.int
                    and self.long == value.long
                    and abs(self.float - value.float) < 0.00000001
                    and self.bool == value.bool
                    and self.none == value.none
                    and self.list == value.list
                    and self.tuple == value.tuple
                    and self.set == value.set
                    and self.dict == value.dict
                    and self.ref == value.ref))

jelly.setUnjellyableForClass(qual(SerializableDummy),
                             SerializableDummy)


class ConverterTest(common.TestCase):
    '''Base classes for convert test cases.

    Sub-classes should override convertion_table() to return
    an iterator on a list of records containing::

        (INPUT_TYPE, [POSSIBLE_INPUT_VALUES],
         OUTPUT_TYPE, [POSSIBLE_OUTPUT_VALUES],
         SHOULD_BE_COPIED)

    To test a pair of converters, one should inherit from this
    base class and override convertion_table() for the pair of
    converters. Then create a class for each conversion
    way inheriting from it, one with the SerializerMixin
    and one with UnserializerMixin.

    These classes have to override setUp() and initialize some attributes:

      - self.serializer : the L{IConverter} to serialize.
      - self.unserializer : the L{IConverter} to unserialize or None.

    Child class can use checkSymmetry() to check the symmetry to check
    symmetry with other serializer/unserializer..

    See test_common_serialization_pytree.py for examples.
    '''

    def testUnserialization(self):

        def inverter(gen):
            while True:
                record = gen.next()
                if len(record) == 5:
                    t1, v1, t2, v2, c = record
                    yield t2, v2, t1, v1, c
                elif len(record) == 7:
                    t1, v1, a1, t2, v2, a2, c = record
                    yield t2, v2, a2, t1, v1, a1, c
                else:
                    print ">"*40, len(record)
                    self.fail("Unexpected conversion table record:\nRECORD: %r"
                              % (record, ))

        if self.unserializer is None:
            raise SkipTest("No unserializer, cannot test convertion")

        self.checkConvertion(inverter(self.convertion_table()),
                             self.unserializer.convert)

    def testSerialization(self):
        if self.serializer is None:
            raise SkipTest("No serializer, cannot test convertion")

        self.checkConvertion(self.convertion_table(),
                             self.serializer.convert)

    def testSymmetry(self):
        if self.unserializer is None:
            raise SkipTest("No unserializer, cannot test for symmetry")

        if self.serializer is None:
            raise SkipTest("No serializer, cannot test for symmetry")

        self.checkSymmetry(self.serializer.convert,
                           self.unserializer.convert)

    def serialize(self, data):
        return self.serializer.convert(data)

    def unserialize(self, data):
        return self.unserializer.convert(data)

    def assertEqualButDifferent(self, value, expected):
        '''Asserts that two value are equal but are different instances.
        It will recurse python structure and object instances
        and ensure everything is equal but different.
        If the expected value contains multiple references to the same value,
        it ensures the other value contains a references to its own value.'''
        self._assertEqualButDifferent(value, expected, 0, {}, {})

    def checkConvertion(self, table, converter):
        for record in table:
            if len(record) == 5:
                _t1, v1, t2, v2, c = record
                values = v1
                exp_type = t2
                exp_values = v2
                should_be_copied = c
            elif len(record) == 7:
                _t1, v1, _a1, t2, v2, a2, c = record
                values = v1
                exp_type = t2
                exp_values = v2 + a2
                should_be_copied = c
            else:
                self.fail("Unexpected conversion table record:\nRECORD: %r"
                          % (record, ))

            for value in values:
                # For each conversion table entries
                # Only check the value, not the alternatives
                self.log("Checking conversion of %r (%s), expecting: %s",
                         value, exp_type.__name__,
                         ", ".join([repr(v) for v in exp_values]))

                result = converter(value)

                # Check type
                self.assertEqual(type(result), exp_type,
                                 "Converted value with type %s instead "
                                 "of %s:\nVALUE: %r"
                                 % (type(result).__name__,
                                    exp_type.__name__, result))

                # Check it's a copy, if required
                if should_be_copied:
                    self.assertIsNot(value, result,
                                     "Input value and converted value "
                                     "are a same instances:\nVALUE: %r"
                                     % (value, ))

                # Look for an expected value
                for expected in exp_values:
                    # For each possible expected values
                    if self.safe_equal(expected, result):
                        break
                else:
                    self.fail("Value not converted to one of the expected "
                              "values:\nVALUE:    %r\nRESULT:   %r\n%s"
                              % (value, result,
                                 "\n".join(["EXPECTED: " + repr(v)
                                            for v in exp_values])))

    def checkSymmetry(self, serializer, deserializer):
        for exp_type, values, must_change in self.symmetry_table():
            for value in values:
                self.log("Checking symmetry for %r (%s)",
                         value, exp_type.__name__)
                self.assertEqual(type(value), exp_type)
                data = serializer(value)
                result = deserializer(data)
                self.assertEqual(type(result), exp_type)
                for v in values:
                    if self.safe_equal(v, result):
                        expected = v
                        break
                else:
                    self.fail("Value not one of the expected values:\n"
                              "VALUE:    %r\nRESULT:   %r\n%s"
                              % (value, result,
                                 "\n".join(["EXPECTED: " + repr(v)
                                            for v in values])))
                if must_change:
                    self.assertEqualButDifferent(result, expected)

    def convertion_table(self):
        raise NotImplementedError()

    def symmetry_table(self):
        # Basic types
        yield int, [0], False
        yield int, [42], False
        yield int, [-42], False
        yield str, [""], False
        yield str, ["spam"], False
        yield unicode, [u""], False
        yield unicode, [u"hétérogénéité"], False
        yield float, [0.0], False
        yield float, [3.14159], False
        yield float, [-3.14159], False
        yield float, [1.231456789e23], False
        yield float, [1.231456789e-23], False
        yield long, [0L], False
        yield long, [2**66], False
        yield long, [-2**66], False
        yield bool, [True], False
        yield bool, [False], False
        yield types.NoneType, [None], False

        # Tuple
        yield tuple, [()], False # Exception for empty tuple singleton
        yield tuple, [(1, 2, 3)], True
        yield tuple, [("a", "b", "c")], True
        yield tuple, [(u"â", u"ê", u"î")], True
        yield tuple, [(0.1, 0.2, 0.3)], True
        yield tuple, [(2**42, 2**43, 2**44)], True
        yield tuple, [(True, False)], True
        yield tuple, [(None, None)], True
        yield tuple, [((), [], set([]), {})], True
        yield tuple, [((1, 2), [3, 4], set([5, 6]), {7: 8})], True

        # List
        yield list, [[]], True
        yield list, [[1, 2, 3]], True
        yield list, [["a", "b", "c"]], True
        yield list, [[u"â", u"ê", u"î"]], True
        yield list, [[0.1, 0.2, 0.3]], True
        yield list, [[2**42, 2**43, 2**44]], True
        yield list, [[True, False]], True
        yield list, [[None, None]], True
        yield list, [[(), [], set([]), {}]], True
        yield list, [[(1, 2), [3, 4], set([5, 6]), {7: 8}]], True

        # Set
        yield set, [set([])], True
        yield set, [set([1, 2, 3])], True
        yield set, [set(["a", "b", "c"])], True
        yield set, [set([u"â", u"ê", u"î"])], True
        yield set, [set([0.1, 0.2, 0.3])], True
        yield set, [set([2**42, 2**43, 2**44])], True
        yield set, [set([True, False])], True
        yield set, [set([None, None])], True
        yield set, [set([()])], True
        yield set, [set([(1, 2)])], True

        # Dictionary
        yield dict, [{}], True
        yield dict, [{1: 2, 3: 4}], True
        yield dict, [{"a": "b", "c": "d"}], True
        yield dict, [{u"â": u"ê", u"î": u"ô"}], True
        yield dict, [{0.1: 0.2, 0.3: 0.4}], True
        yield dict, [{2**42: 2**43, 2**44: 2**45}], True
        yield dict, [{True: False}], True
        yield dict, [{None: None}], True
        yield dict, [{(): ()}], True
        yield dict, [{(1, 2): (3, 4)}], True
        yield dict, [{1: [], 2: set([]), 3: {}}], True
        yield dict, [{1: [2, 3], 4: set([5, 6]), 7: {8: 9}}], True

        # Instances
        yield SerializableDummy, [SerializableDummy()], True

        # Modified instance
        o = SerializableDummy()
        o.str = "spam"
        o.unicode = "fúúúú"
        o.int = 18
        o.long = 2**44
        o.float = 2.7182818284
        o.bool = False
        o.list = ['a', 'b', 'c']
        o.tuple = ('d', 'e', 'f')
        o.set = set(['g', 'h', 'i'])
        o.dict = {'j': 1, 'k': 2, 'l': 3}
        yield SerializableDummy, [o], True

        # Combined test without references
        yield list, [["a", u"b", 2**66, True, False, None,
                     SerializableDummy(),
                     (1, (2, 3), [4, 5], set([6, 7]), {8: 9}),
                     [1, (2, 3), [4, 5], set([6, 7]), {8: 9}],
                     set([1, (2, 3)]),
                     {1: (2, 3), 4: [5, 6], 7: set([8, 9]),
                      10: {11: 12}, (13, 14): 15}]], True

        # Reference in list
        a = ["a", "b"]
        yield list, [[a, a]], True

        # Reference in tuple
        a = (4, 5, 6)
        yield tuple, [(a, a)], True

        # Reference in dictionary value
        a = ("a", )
        yield dict, [{1: a, 2: a}], True

        # Dereference in dictionary keys.
        a = (("x"), )
        yield list, [[a, {a: 1}]], True

        # Reference in dictionary keys.
        a = (66, 42, 18)
        yield list, [[{a: 1}, a]], True

        a = ((), )
        b = {1: a, 2: a, 3: a}
        yield dict, [b], True

        # Multiple reference in dictionary keys
        a = (u"a", )
        b = {(1, a): 1, (2, a): 2, (3, a): 3}
        yield dict, [b], True

        # Dereference in set.
        a = ('x', )
        yield list, [[a, set([a])]], True

        # Reference in set.
        a = (18, )
        yield list, [[set([a]), a]], True

        # Multiple reference in set
        a = (1, False)
        b = set([(1, a), (2, a), (3, a)])
        yield set, [b], True

        # List self-reference
        a = []
        a.append(a)
        yield list, [a], True

        # Dictionary self-reference
        a = {}
        a[1] = a
        yield dict, [a], True

        # Multiple references
        a = ["mumu", "mama", "momo"]
        b = [a]
        c = [a, b]
        yield list, [[a, b, c]], True

        # Complex structure
        a = (42, )
        b = (a, )
        b2 = set(b)
        c = (a, b)
        c2 = {a: b2, b: c}
        d = (a, b, c)
        d2 = [a, b2, c2]
        e = (b, c, d)
        e2 = [b2, c2, e]
        c2[e] = e2 # Make a cycle
        yield dict, [{b: b2, c: c2, d: d2, e: e2}], True

        # complex references in instances
        o1 = SerializableDummy()
        o2 = SerializableDummy()
        o3 = SerializableDummy()
        o1.ref = o2
        o2.ref = o1
        o3.ref = o3
        o1.list = o3.list
        o2.dict = o1.dict
        o3.tuple = o2.tuple

        yield SerializableDummy, [o1], True
        yield SerializableDummy, [o2], True
        yield SerializableDummy, [o3], True
        yield list, [[o1, o3]], True
        yield list, [[o1, o2, o3]], True

    def safe_equal(self, a, b):
        '''Circular references safe comparator.
        The two values must have the same internal references,
        meaning if a contains multiple references to the same
        object, b should equivalent values should be references
        too but do not need to be references to the same object,
        the object just have to be equals.'''
        return self._safe_equal(a, b, 0, {}, {})

    ### Private Methods ###

    def _safe_equal(self, a, b, idx, arefs, brefs):
        if a is b:
            return True

        if type(a) != type(b):
            return False

        if isinstance(a, float):
            return abs(a - b) < 0.000001

        if isinstance(a, (int, long, str, unicode, bool, type(None))):
            return a == b

        aid = id(a)
        bid = id(b)

        if aid in arefs:
            # first value is a reference, check the other value is too
            if bid not in brefs:
                return False
            # Check the two reference the same value inside the structure
            return arefs[aid] == brefs[bid]

        if bid in brefs:
            return False

        arefs[aid] = idx
        brefs[bid] = idx

        if isinstance(a, (tuple, list)):
            if len(a) != len(b):
                return False
            for v1, v2 in zip(a, b):
                if not self._safe_equal(v1, v2, idx + 1, arefs, brefs):
                    return False
                idx += 1
            return True

        if isinstance(a, set):
            if len(a) != len(b):
                return False
            for k1 in a:
                for k2 in b:
                    # We keep a copy of the reference dictionaries
                    # because if the comparison fail we don't want to pollute
                    # them with invalid references
                    acopy = dict(arefs)
                    bcopy = dict(brefs)
                    if self._safe_equal(k1, k2, idx + 1, acopy, bcopy):
                        arefs.update(acopy)
                        brefs.update(bcopy)
                        break
                else:
                    # Not equal key found in b
                    return False
                idx += 1
            return True

        if isinstance(a, dict):
            if len(a) != len(b):
                return False
            for k1, v1 in a.iteritems():
                for k2, v2 in b.iteritems():
                    # We keep a copy of copy of the reference dictionaries
                    # because if the comparison fail we don't want to pollute
                    # them with invalid references
                    acopy = dict(arefs)
                    bcopy = dict(brefs)
                    if self._safe_equal(k1, k2, idx + 1, acopy, bcopy):
                        if not self._safe_equal(v1, v2, idx + 2, arefs, brefs):
                            return False
                        arefs.update(acopy)
                        brefs.update(bcopy)
                        break
                else:
                    # Not key found
                    return False
                idx += 2
            return True

        if hasattr(a, "__dict__"):
            return self._safe_equal(a.__dict__, b.__dict__,
                                    idx + 1, arefs, brefs)

        if hasattr(a, "__slots__"):
            for attr in a.__slots__:
                v1 = getattr(a, attr)
                v2 = getattr(b, attr)
                if not self._safe_equal(v1, v2, idx + 1, arefs, brefs):
                    return False
            return True

        raise RuntimeError("I don't know how to compare %r and %r" % (a, b))

    def _assertEqualButDifferent(self, value, expected, idx, valids, expids):
        '''idx is used to identify every values uniquely to be able to verify
        references are made to the same value, valids and expids are
        dictionaries with instance id() for key and idx for value.'''

        # Only check references for type that can be referenced.
        # Let the immutable type do what they want, sometime strings
        # are interned sometime no, we don't care.
        if not isinstance(expected, (int, long, float, bool,
                                     str, unicode, type(None))):
            # Get unique instance identifiers
            expid = id(expected)
            valid = id(value)

            if expid in expids:
                # Expected value is a reference, check the other value is too
                self.assertTrue(valid in valids)
                # Check the two reference the same value inside the structure
                self.assertEqual(valids[valid], expids[expid])
                return idx

            # Check the other value is not a reference if it wasn't expected
            self.assertFalse(valid in valids)

            # Store the instance identifiers for later checks
            expids[expid] = idx
            valids[valid] = idx

        if expected is None:
            self.assertEqual(expected, value)
        elif isinstance(expected, (list, tuple)):
            if expected != (): # Special case for tuple singleton
                self.assertIsNot(expected, value)
            self.assertEqual(len(expected), len(value))
            for exp, val in zip(expected, value):
                idx = self._assertEqualButDifferent(val, exp, idx + 1,
                                                    valids, expids)
        elif isinstance(expected, set):
            self.assertEqual(len(expected), len(value))
            for exp in expected:
                self.assertTrue(exp in value)
                val = [v for v in value if v == exp][0]
                idx = self._assertEqualButDifferent(val, exp, idx + 1,
                                                    valids, expids)
        elif isinstance(expected, dict):
            self.assertEqual(len(expected), len(value))
            for exp_key, exp_val in expected.items():
                self.assertTrue(exp_key in value)
                val_key = [k for k in value if k == exp_key][0]
                val_val = value[val_key]
                idx = self._assertEqualButDifferent(val_key, exp_key, idx + 1,
                                                    valids, expids)
                idx = self._assertEqualButDifferent(val_val, exp_val, idx + 1,
                                                    valids, expids)
        elif isinstance(value, float):
            self.assertAlmostEqual(value, expected)
        elif isinstance(value, (int, long, bool, str, unicode)):
            self.assertEqual(value, expected)
        else:
            self.assertIsNot(expected, value)
            if ISerializable.providedBy(expected):
                self.assertTrue(ISerializable.providedBy(value))
            idx = self._assertEqualButDifferent(value.__dict__,
                                                expected.__dict__,
                                                idx + 1,
                                                valids, expids)
        return idx
