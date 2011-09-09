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

from feat.common import decorator

from . import common


@decorator.simple_class
def test_simple_class_decorator(cls):
    cls.decorated = True
    return cls


@decorator.parametrized_class
def test_parametrized_class_decorator(cls, *args, **kwargs):
    cls.args = args
    cls.kwargs = kwargs
    return cls


@decorator.simple_function
def test_simple_decorator(callable):

    def wrapper(*args, **kwargs):
        result = callable(*args, **kwargs)
        return "decorated", result

    return wrapper


@decorator.parametrized_function
def test_parametrized_decorator(callable, dec_arg, dec_keyword=None):

    def wrapper(*args, **kwargs):
        result = callable(*args, **kwargs)
        return dec_arg, dec_keyword, result

    return wrapper


@decorator.simple_callable
def test_simple_consistent_decorator(original):

    def wrapper(callable, fun_arg):
        # original is the decorated function (never bounded)
        # callable is a function or a BoundMethod
        return "simple", callable(fun_arg)

    return wrapper


@decorator.parametrized_callable
def test_parametrized_consistent_decorator(original, dec_arg):

    def wrapper(callable, fun_arg):
        # original is the decorated function (never bounded)
        # callable is a function or a BoundMethod
        return dec_arg, callable(fun_arg)

    return wrapper


@test_simple_decorator
def test_simple_fun(val):
    '''test_simple_fun doc'''
    return "test_simple_fun", val


@test_parametrized_decorator(42)
def test_param_fun1(arg):
    '''test_param_fun1 doc'''
    return "test_param_fun1", arg


@test_parametrized_decorator(42, dec_keyword=66)
def test_param_fun2():
    '''test_param_fun2 doc'''
    return "test_param_fun2"


@test_simple_consistent_decorator
def test_simple_cons_fun(arg):
    '''test_simple_cons_fun doc'''
    return "test_simple_cons_fun", arg


@test_parametrized_consistent_decorator(42)
def test_param_cons_fun(arg):
    '''test_param_cons_fun doc'''
    return "test_param_cons_fun", arg


class Dummy(object):

    def __init__(self, name):
        self.name = name

    @test_simple_decorator
    def test_simple_meth(self, val):
        '''test_simple_meth doc'''
        return self.name + ".test_simple_meth", val

    @test_parametrized_decorator(42)
    def test_param_meth1(self, arg):
        '''test_param_meth1 doc'''
        return self.name + ".test_param_meth1", arg

    @test_parametrized_decorator(42, dec_keyword=66)
    def test_param_meth2(self):
        '''test_param_meth2 doc'''
        return self.name + ".test_param_meth2"

    @test_simple_consistent_decorator
    def test_simple_cons_meth(self, arg):
        '''test_simple_cons_meth doc'''
        return self.name + ".test_simple_cons_meth", arg

    @test_parametrized_consistent_decorator(42)
    def test_param_cons_meth(self, arg):
        '''test_param_cons_meth doc'''
        return self.name + ".test_param_cons_meth", arg


@test_simple_class_decorator
class TestSimpleClassDecorator(object):
    decorated = False


@test_parametrized_class_decorator(1, 2, 3, spam="beans", bacon="eggs")
class TestParametrizedClassDecorator(object):
    args = None
    kwargs = None


class TestDecorator(common.TestCase):

    def testSimpleClassDecorator(self):
        self.assertTrue(TestSimpleClassDecorator.decorated)

    def testParametrizedClassDecorator(self):
        self.assertEqual((1, 2, 3), TestParametrizedClassDecorator.args)
        self.assertEqual({"spam": "beans", "bacon": "eggs"},
                         TestParametrizedClassDecorator.kwargs)

    def testSimpleFunctionDecorator(self):
        self.assertEqual(("decorated", ("test_simple_fun", 18)),
                         test_simple_fun(18))
        self.assertEqual("test_simple_fun",
                         test_simple_fun.__name__)
        self.assertEqual("test_simple_fun doc",
                         test_simple_fun.__doc__)

    def testSimpleMethodDecorator(self):
        d = Dummy("dummy")

        self.assertEqual(("decorated", ("dummy.test_simple_meth", 18)),
                         d.test_simple_meth(18))
        self.assertEqual("test_simple_meth",
                         d.test_simple_meth.__name__)
        self.assertEqual("test_simple_meth doc",
                         d.test_simple_meth.__doc__)

    def testParametrizedFunctionDecorator(self):
        self.assertEqual((42, None, ("test_param_fun1", 18)),
                         test_param_fun1(18))
        self.assertEqual("test_param_fun1",
                         test_param_fun1.__name__)
        self.assertEqual("test_param_fun1 doc",
                         test_param_fun1.__doc__)

        self.assertEqual((42, 66, "test_param_fun2"),
                         test_param_fun2())
        self.assertEqual("test_param_fun2",
                         test_param_fun2.__name__)
        self.assertEqual("test_param_fun2 doc",
                         test_param_fun2.__doc__)

        # Test again to detect lazy binding issues
        self.assertEqual((42, None, ("test_param_fun1", 18)),
                         test_param_fun1(18))
        self.assertEqual((42, 66, "test_param_fun2"),
                         test_param_fun2())

    def testParametrizedMethodDecorator(self):
        d = Dummy("dummy")

        self.assertEqual((42, None, ("dummy.test_param_meth1", 18)),
                         d.test_param_meth1(18))
        self.assertEqual("test_param_meth1",
                         d.test_param_meth1.__name__)
        self.assertEqual("test_param_meth1 doc",
                         d.test_param_meth1.__doc__)

        self.assertEqual((42, 66, "dummy.test_param_meth2"),
                         d.test_param_meth2())
        self.assertEqual("test_param_meth2",
                         d.test_param_meth2.__name__)
        self.assertEqual("test_param_meth2 doc",
                         d.test_param_meth2.__doc__)

        # Test again to detect lazy binding issues
        self.assertEqual((42, None, ("dummy.test_param_meth1", 18)),
                         d.test_param_meth1(18))
        self.assertEqual((42, 66, "dummy.test_param_meth2"),
                         d.test_param_meth2())

    def testSimpleConsistentFunctionDecorator(self):
        self.assertEqual(("simple", ("test_simple_cons_fun", 18)),
                         test_simple_cons_fun(18))
        self.assertEqual("test_simple_cons_fun",
                         test_simple_cons_fun.__name__)
        self.assertEqual("test_simple_cons_fun doc",
                         test_simple_cons_fun.__doc__)

        # Test again to detect lazy binding issues
        self.assertEqual(("simple", ("test_simple_cons_fun", 18)),
                         test_simple_cons_fun(18))

    def testSimpleConsistentMethodDecorator(self):
        d = Dummy("dummy")

        self.assertEqual(("simple", ("dummy.test_simple_cons_meth", 18)),
                         d.test_simple_cons_meth(18))
        self.assertEqual("test_simple_cons_meth",
                         d.test_simple_cons_meth.__name__)
        self.assertEqual("test_simple_cons_meth doc",
                         d.test_simple_cons_meth.__doc__)

        # Test again to detect lazy binding issues
        self.assertEqual(("simple", ("dummy.test_simple_cons_meth", 18)),
                         d.test_simple_cons_meth(18))

    def testParametrizedConsistentFunctionDecorator(self):
        self.assertEqual((42, ("test_param_cons_fun", 18)),
                         test_param_cons_fun(18))
        self.assertEqual("test_param_cons_fun",
                         test_param_cons_fun.__name__)
        self.assertEqual("test_param_cons_fun doc",
                         test_param_cons_fun.__doc__)

        # Test again to detect lazy binding issues
        self.assertEqual((42, ("test_param_cons_fun", 18)),
                         test_param_cons_fun(18))

    def testParametrizedConsistentMethodDecorator(self):
        d = Dummy("dummy")

        self.assertEqual((42, ("dummy.test_param_cons_meth", 18)),
                         d.test_param_cons_meth(18))
        self.assertEqual("test_param_cons_meth",
                         d.test_param_cons_meth.__name__)
        self.assertEqual("test_param_cons_meth doc",
                         d.test_param_cons_meth.__doc__)

        # Test again to detect lazy binding issues
        self.assertEqual((42, ("dummy.test_param_cons_meth", 18)),
                         d.test_param_cons_meth(18))
