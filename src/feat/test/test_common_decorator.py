# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from feat.common import decorator

from . import common


@decorator.simple
def test_simple_decorator(callable):

    def wrapper(*args, **kwargs):
        result = callable(*args, **kwargs)
        return "decorated", result

    return wrapper

@decorator.with_arguments
def test_normal_decorator(callable, dec_arg, dec_keyword=None):

    def wrapper(*args, **kwargs):
        result = callable(*args, **kwargs)
        return dec_arg, dec_keyword, result

    return wrapper

@decorator.consistent
def test_consistent_decorator(original, dec_arg):

    def wrapper(callable, fun_arg):
        # original is the decorated function (never bounded)
        # callable is a function or a BoundMethod
        return dec_arg, callable(fun_arg)

    return wrapper


@test_simple_decorator
def test_simple_fun(val):
    '''test_simple_fun doc'''
    return "test_simple_fun", val

@test_normal_decorator(42)
def test_norm_fun1(arg):
    '''test_norm_fun1 doc'''
    return "test_norm_fun1", arg

@test_normal_decorator(42, dec_keyword=66)
def test_norm_fun2():
    '''test_norm_fun2 doc'''
    return "test_norm_fun2"

@test_consistent_decorator(42)
def test_cons_fun(arg):
    '''test_cons_fun doc'''
    return "test_cons_fun", arg


class Dummy(object):

    def __init__(self, name):
        self.name = name

    @test_simple_decorator
    def test_simple_meth(self, val):
        '''test_simple_meth doc'''
        return self.name + ".test_simple_meth", val

    @test_normal_decorator(42)
    def test_norm_meth1(self, arg):
        '''test_norm_meth1 doc'''
        return self.name + ".test_norm_meth1", arg

    @test_normal_decorator(42, dec_keyword=66)
    def test_norm_meth2(self):
        '''test_norm_meth2 doc'''
        return self.name + ".test_norm_meth2"

    @test_consistent_decorator(42)
    def test_cons_meth(self, arg):
        '''test_cons_meth doc'''
        return self.name + ".test_cons_meth", arg


class TestDecorator(common.TestCase):

    def testSimpleDecorator(self):
        d = Dummy("dummy")

        self.assertEqual(("decorated", ("test_simple_fun", 18)),
                         test_simple_fun(18))
        self.assertEqual("test_simple_fun", test_simple_fun.__name__)
        self.assertEqual("test_simple_fun doc", test_simple_fun.__doc__)

        self.assertEqual(("decorated", ("dummy.test_simple_meth", 18)),
                         d.test_simple_meth(18))
        self.assertEqual("test_simple_meth", d.test_simple_meth.__name__)
        self.assertEqual("test_simple_meth doc", d.test_simple_meth.__doc__)

    def testNormalFunctionDecorator(self):
        self.assertEqual((42, None, ("test_norm_fun1", 18)), test_norm_fun1(18))
        self.assertEqual("test_norm_fun1", test_norm_fun1.__name__)
        self.assertEqual("test_norm_fun1 doc", test_norm_fun1.__doc__)

        self.assertEqual((42, 66, "test_norm_fun2"), test_norm_fun2())
        self.assertEqual("test_norm_fun2", test_norm_fun2.__name__)
        self.assertEqual("test_norm_fun2 doc", test_norm_fun2.__doc__)

        # Test again to detect lazy binding issues
        self.assertEqual((42, None, ("test_norm_fun1", 18)), test_norm_fun1(18))
        self.assertEqual((42, 66, "test_norm_fun2"), test_norm_fun2())


    def testNormalMethodDecorator(self):
        d = Dummy("dummy")

        self.assertEqual((42, None, ("dummy.test_norm_meth1", 18)),
                         d.test_norm_meth1(18))
        self.assertEqual("test_norm_meth1", d.test_norm_meth1.__name__)
        self.assertEqual("test_norm_meth1 doc", d.test_norm_meth1.__doc__)

        self.assertEqual((42, 66, "dummy.test_norm_meth2"), d.test_norm_meth2())
        self.assertEqual("test_norm_meth2", d.test_norm_meth2.__name__)
        self.assertEqual("test_norm_meth2 doc", d.test_norm_meth2.__doc__)

        # Test again to detect lazy binding issues
        self.assertEqual((42, None, ("dummy.test_norm_meth1", 18)),
                         d.test_norm_meth1(18))
        self.assertEqual((42, 66, "dummy.test_norm_meth2"), d.test_norm_meth2())

    def testConsistentFunctionDecorator(self):
        self.assertEqual((42, ("test_cons_fun", 18)), test_cons_fun(18))
        self.assertEqual("test_cons_fun", test_cons_fun.__name__)
        self.assertEqual("test_cons_fun doc", test_cons_fun.__doc__)

        # Test again to detect lazy binding issues
        self.assertEqual((42, ("test_cons_fun", 18)), test_cons_fun(18))

    def testConsistentMethodDecorator(self):
        d = Dummy("dummy")

        self.assertEqual((42, ("dummy.test_cons_meth", 18)),
                         d.test_cons_meth(18))
        self.assertEqual("test_cons_meth", d.test_cons_meth.__name__)
        self.assertEqual("test_cons_meth doc", d.test_cons_meth.__doc__)

        # Test again to detect lazy binding issues
        self.assertEqual((42, ("dummy.test_cons_meth", 18)),
                         d.test_cons_meth(18))
