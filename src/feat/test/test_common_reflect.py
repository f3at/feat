# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from feat.common import reflect

from . import common


def test_depth2(depth=2):
    return  reflect.class_locals(depth)


def test_depth3(depth=3):
    return  test_depth2(depth=depth)


try:
    meta_test1_pass = True

    class MetaError1(object):

        class_local = True

        if "class_local" not in reflect.class_locals(1):
            raise RuntimeError()

        if "class_local" not in test_depth2():
            raise RuntimeError()

        if "class_local" not in test_depth3():
            raise RuntimeError()

except RuntimeError:
    meta_test1_pass = False


try:
    meta_test2_pass = False

    class MetaError2(object):

        if "class_local" not in test_depth2(depth=3):
            raise RuntimeError()

except TypeError, e:
    meta_test2_pass = True


try:
    meta_test3_pass = False

    class MetaError2(object):

        if "class_local" not in test_depth2(depth=1):
            raise RuntimeError()

except TypeError:
    meta_test3_pass = True


meta_test4_pass = not reflect.inside_class_definition(1)


class MetaError3(object):

    bad1 = reflect.inside_class_definition(0)
    good = reflect.inside_class_definition(1)
    bad2 = reflect.inside_class_definition(2)


class Dummy(object):

    def spam(self):
        pass


def bacon():
    pass


class TestIntrospection(common.TestCase):

    def testMetaErrors(self):
        self.assertTrue(meta_test1_pass)
        self.assertTrue(meta_test2_pass)
        self.assertTrue(meta_test3_pass)
        self.assertTrue(meta_test4_pass)
        self.assertFalse(MetaError3.bad1)
        self.assertTrue(MetaError3.good)
        self.assertFalse(MetaError3.bad2)

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
