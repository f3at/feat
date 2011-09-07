# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.
# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from feat.common import reflect

from zope.interface import Interface

from . import common


class DummyInterface(Interface):
    pass


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

    name = reflect.class_canonical_name(depth=1)

    def spam(self):
        pass


def bacon():
    pass


class Meta(type):
    pass


class MetaDummy(object):
    __metaclass__ = Meta


class TestIntrospection(common.TestCase):

    def testMetaErrors(self):
        self.assertTrue(meta_test1_pass)
        self.assertTrue(meta_test2_pass)
        self.assertTrue(meta_test3_pass)
        self.assertTrue(meta_test4_pass)
        self.assertFalse(MetaError3.bad1)
        self.assertTrue(MetaError3.good)
        self.assertFalse(MetaError3.bad2)

    def testInterface(self):
        self.assertEqual("feat.test.test_common_reflect.DummyInterface",
                         reflect.canonical_name(DummyInterface))

    def testClass(self):
        self.assertEqual("feat.test.test_common_reflect.Dummy",
                         reflect.canonical_name(Dummy))
        self.assertEqual("feat.test.test_common_reflect.Dummy",
                         reflect.canonical_name(Dummy()))
        self.assertEqual("__builtin__.int",
                         reflect.canonical_name(int))
        self.assertEqual("__builtin__.str",
                         reflect.canonical_name("some string"))

    def testClassMithMeta(self):
        self.assertEqual("feat.test.test_common_reflect.MetaDummy",
                         reflect.canonical_name(MetaDummy))

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

    def testGettingCanonicalNameFromClass(self):
        self.assertEqual('feat.test.test_common_reflect.Dummy',
                         Dummy.name)

    def testFormatedFunctionName(self):
        self.assertEqual('simple(a, b)',
                         reflect.formatted_function_name(simple))
        self.assertEqual('defaults(a, b=3)',
                         reflect.formatted_function_name(defaults))
        self.assertEqual('varargs(a, b=None, *args)',
                         reflect.formatted_function_name(varargs))
        self.assertEqual('kwargs(a=None, b=3, *args, **kwargs)',
                         reflect.formatted_function_name(kwargs))


def simple(a, b):
    pass


def defaults(a, b=3):
    pass


def varargs(a, b=None, *args):
    pass


def kwargs(a=None, b=3, *args, **kwargs):
    pass
