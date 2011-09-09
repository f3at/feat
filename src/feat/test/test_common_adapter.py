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
