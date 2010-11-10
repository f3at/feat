# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from feat.common import reflect

from . import common


class Dummy(object):

    def spam(self):
        pass


def bacon():
    pass


class TestIntrospection(common.TestCase):

    def testClass(self):
        self.assertEqual("feat.test.test_common_reflect.Dummy",
                         reflect.canonical_name(Dummy))
        self.assertEqual("feat.test.test_common_reflect.Dummy",
                         reflect.canonical_name(Dummy()))
        self.assertEqual("__builtin__.int",
                         reflect.canonical_name(int))
        self.assertEqual("__builtin__.str",
                         reflect.canonical_name("some string"))

    def testMethod(self):
        self.assertEqual("feat.test.test_common_reflect.Dummy.spam",
                         reflect.canonical_name(Dummy.spam))
        self.assertEqual("feat.test.test_common_reflect.Dummy.spam",
                         reflect.canonical_name(Dummy().spam))

        self.assertEqual("__builtin__.split",
                         reflect.canonical_name("test".split))

    def testFunction(self):
        self.assertEqual("feat.test.test_common_reflect.bacon",
                         reflect.canonical_name(bacon))

        self.assertEqual("__builtin__.getattr",
                         reflect.canonical_name(getattr))

    def testNone(self):
        self.assertEqual(None, reflect.canonical_name(None))
