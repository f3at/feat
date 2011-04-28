# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from twisted.python import failure

from feat.common import serialization, adapter
from feat.common.serialization import base, sexp

from feat.interface.serialization import *

from . import common


class DummyError(Exception):

    def __init__(self, custom, values, *args):
        Exception.__init__(self, *args)
        self.custom = custom
        self.value = values


class TestAdapters(common.TestCase):

    def setUp(self):
        self.serializer = sexp.Serializer()
        self.unserializer = sexp.Unserializer()

    def pingpong(self, value):
        data = self.serializer.convert(value)
        return self.unserializer.convert(data)

    def testExceptionAdapter(self):
        value1 = ValueError("some", "argument", 42)
        result1a = self.pingpong(value1)
        self.assertTrue(isinstance(result1a, type(value1)))
        self.assertEqual(result1a, value1)
        result1b = self.pingpong(result1a)
        self.assertTrue(isinstance(result1b, type(value1)))
        self.assertEqual(result1b, value1)
        self.assertEqual(result1b, result1a)
        self.assertEqual(type(result1b), type(result1a))
        self.assertEqual(type(result1a).__bases__[0], type(value1))
        self.assertEqual(type(result1b).__bases__[0], type(value1))

        value2 = DummyError("some", "argument", 42)
        result2 = self.pingpong(value2)
        self.assertTrue(isinstance(result2, type(value2)))
        self.assertEqual(result2, value2)

        self.assertNotEqual(result1a, result2)

    def testFailures(self):
        # Create a true failure
        try:
            1 + ""
        except TypeError, e:
            value1 = failure.Failure(e)

        result1a = self.pingpong(value1)
        self.assertTrue(issubclass(type(result1a), failure.Failure))
        self.assertEqual(result1a, value1)
        result1b = self.pingpong(result1a)
        self.assertTrue(isinstance(result1b, failure.Failure))
        self.assertEqual(result1b, value1)
        self.assertEqual(result1b, result1a)
        self.assertEqual(type(result1b), type(result1a))
        self.assertEqual(type(result1a).__bases__[0], failure.Failure)
        self.assertEqual(type(result1b).__bases__[0], failure.Failure)
