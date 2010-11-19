# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from zope.interface import Interface, implements

from feat.common import adapter

from . import common


class IFoo(Interface):
    pass


class IBar(Interface):
    pass


@adapter.register(IFoo, IBar)
class Foo2Bar(object):

    implements(IBar)

    def __init__(self, foo):
        # Should fail if foo is not IFoo
        self.foo = IFoo(foo)


@adapter.register(int, IFoo)
class Int2Foo(object):

    implements(IFoo)

    def __init__(self, value):
        if not isinstance(value, int):
            raise TypeError()
        self.value = value


class TestIntrospection(common.TestCase):

    def testAdaptation(self):
        # Check type errors
        self.assertRaises(TypeError, Int2Foo, "bad")
        self.assertRaises(TypeError, Foo2Bar, "bad")

        # Manual adaptation
        Foo2Bar(Int2Foo(42))

        self.assertTrue(isinstance(IFoo(18), Int2Foo))
        self.assertTrue(isinstance(IBar(Int2Foo(18)), Foo2Bar))
