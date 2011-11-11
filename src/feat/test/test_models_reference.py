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

from zope.interface import implements

from feat.models import interface, reference

from . import common


class DummyModel(object):

    implements(interface.IModel)

    def __init__(self, identity):
        self.identity = identity


class Context(object):

    implements(interface.IContext)

    def __init__(self, idents, names, remaining):
        self.models = [DummyModel(i) for i in idents]
        self.names = tuple([unicode(i) for i in names])
        self.remaining = tuple([unicode(i) for i in remaining])


class TestModelsReference(common.TestCase):

    def testAbsoluteReference(self):
        Ref = reference.Absolute
        Ctx = Context

        ref = Ref("dummy", "a", "b")
        self.assertTrue(interface.IReference.providedBy(ref))
        self.assertTrue(interface.IAbsoluteReference.providedBy(ref))
        self.assertTrue(isinstance(ref.root, unicode))
        self.assertTrue(isinstance(ref.location, tuple))
        self.assertTrue(isinstance(ref.location[0], unicode))
        self.assertTrue(isinstance(ref.location[1], unicode))
        self.assertEqual(Ref("test").root, u"test")
        self.assertEqual(Ref("X").location, ())
        self.assertEqual(Ref("X", "a", "b", "c").location, (u"a", u"b", u"c"))

        ref = Ref("RR")
        ctx = Ctx(("root", ), ("CR", ), ())
        self.assertEqual(ref.resolve(ctx), ("RR", ))
        ctx = Ctx(("root", "Z", "Y"), ("CR", "z", "y"), ())
        self.assertEqual(ref.resolve(ctx), ("RR", ))

        ref = Ref("RR", "a", "b")
        ctx = Ctx(("root", "Z", "Y"), ("CR", "z", "y"), ())
        self.assertEqual(ref.resolve(ctx), ("RR", "a", "b"))
        ctx = Ctx(("root", "Z", "Y"), ("CR", "z", "y"), ("x", "w"))
        self.assertEqual(ref.resolve(ctx), ("RR", "a", "b", "x", "w"))

    def testLocalReference(self):
        Ref = reference.Local
        Ctx = Context

        ref = Ref("a", "b")
        self.assertTrue(interface.IReference.providedBy(ref))
        self.assertTrue(interface.ILocalReference.providedBy(ref))
        self.assertTrue(isinstance(ref.location, tuple))
        self.assertTrue(isinstance(ref.location[0], unicode))
        self.assertTrue(isinstance(ref.location[1], unicode))
        self.assertEqual(ref.location, (u"a", u"b"))

        ref = Ref()
        ctx = Ctx(("root", ), ("CR", ), ())
        self.assertEqual(ref.resolve(ctx), ("CR", ))
        ctx = Ctx(("root", "Z", "Y"), ("CR", "z", "y"), ())
        self.assertEqual(ref.resolve(ctx), ("CR", ))

        ref = Ref("a", "b")
        ctx = Ctx(("root", "Z", "Y"), ("CR", "z", "y"), ())
        self.assertEqual(ref.resolve(ctx), ("CR", "a", "b"))
        ctx = Ctx(("root", "Z", "Y"), ("CR", "z", "y"), ("x", "w"))
        self.assertEqual(ref.resolve(ctx), ("CR", "a", "b", "x", "w"))

    def testRelativeReference(self):
        Ref = reference.Relative
        Ctx = Context

        ref = Ref("a", "b")
        self.assertTrue(interface.IReference.providedBy(ref))
        self.assertTrue(interface.IRelativeReference.providedBy(ref))
        self.assertEqual(ref.base, None)
        self.assertTrue(isinstance(ref.location, tuple))
        self.assertTrue(isinstance(ref.location[0], unicode))
        self.assertTrue(isinstance(ref.location[1], unicode))
        self.assertEqual(ref.location, (u"a", u"b"))

        ref = Ref("a", "b", base="foo")
        self.assertTrue(isinstance(ref.base, unicode))
        self.assertEqual(ref.base, u"foo")
        self.assertEqual(ref.location, (u"a", u"b"))

        ref = Ref()
        ctx = Ctx(("root", ), ("CR", ), ())
        self.assertEqual(ref.resolve(ctx), ("CR", ))
        ctx = Ctx(("root", "Z", "Y"), ("CR", "z", "y"), ())
        self.assertEqual(ref.resolve(ctx), ("CR", "z", "y"))
        ctx = Ctx(("root", "Z", "Y"), ("CR", "z", "y"), ("x", "w"))
        self.assertEqual(ref.resolve(ctx), ("CR", "z", "y", "x", "w"))

        ref = Ref("a", "b")
        ctx = Ctx(("root", ), ("CR", ), ())
        self.assertEqual(ref.resolve(ctx), ("CR", "a", "b"))
        ctx = Ctx(("root", "Z", "Y"), ("CR", "z", "y"), ())
        self.assertEqual(ref.resolve(ctx), ("CR", "z", "y", "a", "b"))
        ctx = Ctx(("root", "Z", "Y"), ("CR", "z", "y"), ("x", "w"))
        self.assertEqual(ref.resolve(ctx),
                         ("CR", "z", "y", "a", "b", "x", "w"))

        ref = Ref(base="Z")
        ctx = Ctx(("root", ), ("CR", ), ())
        self.assertRaises(interface.BadReference, ref.resolve, ctx)
        ctx = Ctx(("root", "Z", "Y"), ("CR", "z", "y"), ())
        self.assertEqual(ref.resolve(ctx), ("CR", "z"))
        ctx = Ctx(("root", "Z", "Y"), ("CR", "z", "y"), ("x", "w"))
        self.assertEqual(ref.resolve(ctx), ("CR", "z", "x", "w"))

        ref = Ref("a", "b", base="Z")
        ctx = Ctx(("root", ), ("CR", ), ())
        self.assertRaises(interface.BadReference, ref.resolve, ctx)
        ctx = Ctx(("root", "Z", "Y"), ("CR", "z", "y"), ())
        self.assertEqual(ref.resolve(ctx), ("CR", "z", "a", "b"))
        ctx = Ctx(("root", "Z", "Y"), ("CR", "z", "y"), ("x", "w"))
        self.assertEqual(ref.resolve(ctx),
                         ("CR", "z", "a", "b", "x", "w"))
