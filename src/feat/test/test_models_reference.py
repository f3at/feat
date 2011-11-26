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
from feat.web import http

from feat.test import common


class DummyModel(object):

    implements(interface.IModel)

    def __init__(self, identity):
        self.identity = identity


class Context(object):

    implements(interface.IContext)

    def __init__(self, idents, names, remaining):
        self.models = [DummyModel(i) for i in idents]
        self.names = (names[0], ) + tuple([unicode(i) for i in names[1:]])
        self.remaining = tuple([unicode(i) for i in remaining])

    def make_action_address(self, action):
        return self.make_model_address(self.names + (action.name, ))

    def make_model_address(self, location):
        host, port = location[0]
        path = "/" + http.tuple2path(location[1:])
        return http.compose(host=host, port=port, path=path)


class TestModelsReference(common.TestCase):

    def testAbsoluteReference(self):
        Ref = reference.Absolute
        Ctx = Context

        ref = Ref(("dummy.com", "44"), "a", "b")
        self.assertTrue(interface.IReference.providedBy(ref))
        self.assertTrue(interface.IAbsoluteReference.providedBy(ref))
        self.assertTrue(isinstance(ref.root, tuple))
        self.assertTrue(isinstance(ref.location, tuple))
        self.assertTrue(isinstance(ref.location[0], unicode))
        self.assertTrue(isinstance(ref.location[1], unicode))
        self.assertEqual(Ref("test.net").root, u"test.net")
        self.assertEqual(Ref(("test.net", 44)).root, ("test.net", 44))
        self.assertEqual(Ref("X").location, ())
        self.assertEqual(Ref("X", "a", "b", "c").location, (u"a", u"b", u"c"))

        ref = Ref(("root.com", 44))
        ctx = Ctx(("RR", ), ("dummy.net", ), ())
        self.assertEqual(ref.resolve(ctx), "http://root.com:44/")
        ctx = Ctx(("RR", "Z", "Y"), ("dummy.net", "z", "y"), ())
        self.assertEqual(ref.resolve(ctx), "http://root.com:44/")

        ref = Ref(("root.com", 44), "a", "b")
        ctx = Ctx((("root", None), "Z", "Y"),
                  ("dummy.net", "z", "y"), ())
        self.assertEqual(ref.resolve(ctx), "http://root.com:44/a/b")
        ctx = Ctx((("root", 44), "Z", "Y"),
                  (("dummy.net", None), "z", "y"), ("x", "w"))
        self.assertEqual(ref.resolve(ctx), "http://root.com:44/a/b/x/w")

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
        ctx = Ctx(("root", ), (("dummy.net", None), ), ())
        self.assertEqual(ref.resolve(ctx), "http://dummy.net/")
        ctx = Ctx(("root", "Z", "Y"), (("dummy.net", None), "z", "y"), ())
        self.assertEqual(ref.resolve(ctx), "http://dummy.net/")

        ref = Ref("a", "b")
        ctx = Ctx(("root", "Z", "Y"),
                  (("dummy.net", None), "z", "y"), ())
        self.assertEqual(ref.resolve(ctx), "http://dummy.net/a/b")
        ctx = Ctx(("root", "Z", "Y"),
                  (("dummy.net", None), "z", "y"), ("x", "w"))
        self.assertEqual(ref.resolve(ctx), "http://dummy.net/a/b/x/w")

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
        ctx = Ctx(("root", ), (("dummy.net", 44), ), ())
        self.assertEqual(ref.resolve(ctx), "http://dummy.net:44/")
        ctx = Ctx(("root", "Z", "Y"),
                  (("dummy.net", 44), "z", "y"), ())
        self.assertEqual(ref.resolve(ctx), "http://dummy.net:44/z/y")
        ctx = Ctx(("root", "Z", "Y"),
                  (("dummy.net", 44), "z", "y"), ("x", "w"))
        self.assertEqual(ref.resolve(ctx), "http://dummy.net:44/z/y/x/w")

        ref = Ref("a", "b")
        ctx = Ctx(("root", ), (("dummy.net", None), ), ())
        self.assertEqual(ref.resolve(ctx), "http://dummy.net/a/b")
        ctx = Ctx(("root", "Z", "Y"),
                  (("dummy.net", None), "z", "y"), ())
        self.assertEqual(ref.resolve(ctx), "http://dummy.net/z/y/a/b")
        ctx = Ctx(("root", "Z", "Y"),
                  (("dummy.net", None), "z", "y"), ("x", "w"))
        self.assertEqual(ref.resolve(ctx), "http://dummy.net/z/y/a/b/x/w")

        ref = Ref(base="Z")
        ctx = Ctx(("root", ), (("dummy.net", None), ), ())
        self.assertRaises(interface.BadReference, ref.resolve, ctx)
        ctx = Ctx(("root", "Z", "Y"),
                  (("dummy.net", None), "z", "y"), ())
        self.assertEqual(ref.resolve(ctx), "http://dummy.net/z")
        ctx = Ctx(("root", "Z", "Y"),
                  (("dummy.net", None), "z", "y"), ("x", "w"))
        self.assertEqual(ref.resolve(ctx), "http://dummy.net/z/x/w")

        ref = Ref("a", "b", base="Z")
        ctx = Ctx(("root", ), (("dummy.net", None), ), ())
        self.assertRaises(interface.BadReference, ref.resolve, ctx)
        ctx = Ctx(("root", "Z", "Y"),
                  (("dummy.net", None), "z", "y"), ())
        self.assertEqual(ref.resolve(ctx), "http://dummy.net/z/a/b")
        ctx = Ctx(("root", "Z", "Y"),
                  (("dummy.net", None), "z", "y"), ("x", "w"))
        self.assertEqual(ref.resolve(ctx), "http://dummy.net/z/a/b/x/w")
