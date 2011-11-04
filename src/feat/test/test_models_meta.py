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

from feat.models import interface, meta

from . import common


class A(meta.Metadata):
    meta.meta("foo", "1")
    meta.meta("bar", "2", "int")


class B(A):
    meta.meta("foo", "3")
    meta.meta("biz", "4")


class C(A):
    meta.meta("booz", "5")
    meta.meta("bar", "6")


class D(C):
    meta.meta("booz", "7")
    meta.meta("foo", "8", "num")
    meta.meta("fez", "9")


class DummyAspect(meta.Metadata):
    meta.meta("foo", "asp1-cls")
    meta.meta("fez", "asp1-cls")


class DummyAspectWithAspect(meta.Metadata):
    meta.meta("fez", "asp2-cls")
    meta.meta("booz", "asp2-cls")

    def __init__(self, aspect=None):
        self.aspect = aspect


class DummyMetaWithAspect(meta.Metadata):
    meta.meta("foo", "meta-cls")
    meta.meta("bar", "meta-cls")

    def __init__(self, aspect=None):
        self.aspect = aspect


class TestModelsMeta(common.TestCase):

    def check_meta(self, meta, expected_values=None):
        self.assertTrue(isinstance(meta, list))
        for m in meta:
            self.assertTrue(interface.IMetadataItem.providedBy(m))
            self.assertTrue(isinstance(m.name, unicode))
            self.assertTrue(isinstance(m.value, unicode))
            self.assertTrue(m.scheme is None or isinstance(m.scheme, unicode))
        if expected_values is not None:
            self.assertEqual(len(meta), len(expected_values))
            for m, e in zip(meta, expected_values):
                self.assertEqual(m, e)

    def testAspectWithoutMeta(self):
        M = meta.MetadataItem
        m = DummyMetaWithAspect(object())

        self.assertEqual(set(m.iter_meta_names()),
                         set(["foo", "bar"]))
        self.assertEqual(set(m.iter_meta()),
                         set([M("foo", "meta-cls"),
                              M("bar", "meta-cls")]))
        self.assertEqual(set(m.iter_meta(u"foo", "fez")),
                         set([M("foo", "meta-cls")]))
        self.assertEqual(set(m.get_meta("bar")),
                         set([M("bar", "meta-cls")]))
        self.assertEqual(set(m.get_meta("fez")),
                         set([]))

    def testAspectMeta(self):
        M = meta.MetadataItem
        a1 = DummyAspect()
        a2 = DummyAspectWithAspect(a1)
        m = DummyMetaWithAspect(a2)

        a1._put_meta("bar", "asp1-ins")
        a1._put_meta("toto", "asp1-ins")

        a2._put_meta("foo", "asp2-ins")
        a2._put_meta("tata", "asp2-ins")

        m._put_meta("booz", "meta-ins")
        m._put_meta("titi", "meta-ins")


        self.assertEqual(set(m.iter_meta_names()),
                         set(["foo", "bar", "fez", "booz",
                              "toto", "tata", "titi"]))
        self.assertEqual(set(m.iter_meta()),
                         set([M("foo", "meta-cls"),
                              M("bar", "meta-cls"),
                              M("fez", "asp2-cls"),
                              M("booz", "asp2-cls"),
                              M("foo", "asp1-cls"),
                              M("fez", "asp1-cls"),
                              M("booz", "meta-ins"),
                              M("titi", "meta-ins"),
                              M("foo", "asp2-ins"),
                              M("tata", "asp2-ins"),
                              M("bar", "asp1-ins"),
                              M("toto", "asp1-ins")]))
        self.assertEqual(set(m.iter_meta(u"tata", "fez", u"spam", "booz")),
                         set([M("fez", "asp2-cls"),
                              M("booz", "asp2-cls"),
                              M("fez", "asp1-cls"),
                              M("booz", "meta-ins"),
                              M("tata", "asp2-ins")]))
        self.assertEqual(set(m.get_meta("foo")),
                         set([M("foo", "meta-cls"),
                              M("foo", "asp1-cls"),
                              M("foo", "asp2-ins")]))
        self.assertEqual(set(m.iter_meta(u"booz")),
                         set([M("booz", "asp2-cls"),
                              M("booz", "meta-ins")]))
        self.assertEqual(set(m.get_meta("spam")),
                         set([]))

    def testClassMeta(self):
        M = meta.MetadataItem
        a = A()
        b = B()
        c = C()
        d = D()

        self.assertTrue(interface.IMetadata.providedBy(a))
        self.assertTrue(interface.IMetadata.providedBy(b))
        self.assertTrue(interface.IMetadata.providedBy(c))
        self.assertTrue(interface.IMetadata.providedBy(d))

        self.check_meta(a.get_meta("foo"), [M("foo", "1")])
        self.check_meta(a.get_meta("bar"), [M("bar", "2", "int")])
        self.assertEqual(a.get_meta("biz"), [])
        self.assertEqual(a.get_meta("booz"), [])
        self.assertEqual(a.get_meta("fez"), [])
        self.assertEqual(a.get_meta("spam"), [])

        self.check_meta(b.get_meta("foo"), [M("foo", "1"), M("foo", "3")])
        self.check_meta(b.get_meta("bar"), [M("bar", "2", "int")])
        self.check_meta(b.get_meta("biz"), [M("biz", "4")])
        self.assertEqual(b.get_meta("booz"), [])
        self.assertEqual(b.get_meta("fez"), [])
        self.assertEqual(b.get_meta("spam"), [])

        self.check_meta(c.get_meta("foo"), [M("foo", "1")])
        self.check_meta(c.get_meta("bar"),
                        [M("bar", "2", "int"), M("bar", "6")])
        self.assertEqual(c.get_meta("biz"), [])
        self.check_meta(c.get_meta("booz"), [M("booz", "5")])
        self.assertEqual(c.get_meta("fez"), [])
        self.assertEqual(c.get_meta("spam"), [])

        self.check_meta(d.get_meta("foo"),
                        [M("foo", "1"), M("foo", "8", "num")])
        self.check_meta(d.get_meta("bar"),
                        [M("bar", "2", "int"), M("bar", "6")])
        self.assertEqual(d.get_meta("biz"), [])
        self.check_meta(d.get_meta("booz"), [M("booz", "5"), M("booz", "7")])
        self.check_meta(d.get_meta("fez"), [M("fez", "9")])
        self.assertEqual(d.get_meta("spam"), [])

        self.assertEqual(set(a.iter_meta()),
                         set([M("foo", "1"), M("bar", "2", "int")]))
        self.assertEqual(set(b.iter_meta()),
                         set([M("foo", "1"), M("bar", "2", "int"),
                              M("foo", "3"), M("biz", "4")]))
        self.assertEqual(set(c.iter_meta()),
                         set([M("foo", "1"), M("bar", "2", "int"),
                              M("bar", "6"), M("booz", "5")]))
        self.assertEqual(set(d.iter_meta()),
                         set([M("foo", "1"), M("bar", "2", "int"),
                              M("bar", "6"), M("booz", "5"),
                              M("booz", "7"), M("foo", "8", "num"),
                              M("fez", "9")]))

        self.assertEqual(set(a.iter_meta_names()),
                         set(["foo", "bar"]))
        self.assertEqual(set(b.iter_meta_names()),
                         set(["foo", "bar", "biz"]))
        self.assertEqual(set(c.iter_meta_names()),
                         set(["foo", "bar", "booz"]))
        self.assertEqual(set(d.iter_meta_names()),
                         set(["foo", "bar", "booz", "fez"]))

        self.assertEqual(set(a.iter_meta("spam")), set())
        self.assertEqual(set(b.iter_meta("spam")), set())
        self.assertEqual(set(c.iter_meta("spam")), set())
        self.assertEqual(set(d.iter_meta("spam")), set())

        self.assertEqual(set(a.iter_meta("foo")),
                         set([M("foo", "1")]))
        self.assertEqual(set(b.iter_meta(u"foo")),
                         set([M("foo", "1"), M("foo", "3")]))
        self.assertEqual(set(c.iter_meta("foo")),
                         set([M("foo", "1")]))
        self.assertEqual(set(d.iter_meta(u"foo")),
                         set([M("foo", "1"), M("foo", "8", "num")]))

        self.assertEqual(set(a.iter_meta("bar")),
                         set([M("bar", "2", "int")]))
        self.assertEqual(set(b.iter_meta(u"bar")),
                         set([M("bar", "2", "int")]))
        self.assertEqual(set(c.iter_meta("bar")),
                         set([M("bar", "2", "int"), M("bar", "6")]))
        self.assertEqual(set(d.iter_meta(u"bar")),
                         set([M("bar", "2", "int"), M("bar", "6")]))

        self.assertEqual(set(a.iter_meta("booz")),
                         set([]))
        self.assertEqual(set(b.iter_meta(u"booz")),
                         set([]))
        self.assertEqual(set(c.iter_meta("booz")),
                         set([M("booz", "5")]))
        self.assertEqual(set(d.iter_meta(u"booz")),
                         set([M("booz", "5"), M("booz", "7")]))

        self.assertEqual(set(a.iter_meta("booz", "spam", u"bar")),
                         set([M("bar", "2", "int")]))
        self.assertEqual(set(b.iter_meta("booz", "spam", u"bar")),
                         set([M("bar", "2", "int")]))
        self.assertEqual(set(c.iter_meta("booz", "spam", u"bar")),
                         set([M("bar", "2", "int"),
                              M("bar", "6"), M("booz", "5")]))
        self.assertEqual(set(d.iter_meta("booz", "spam", u"bar")),
                         set([M("bar", "2", "int"),
                              M("bar", "6"), M("booz", "5"),
                              M("booz", "7")]))

    def testInstanceMeta(self):
        M = meta.MetadataItem
        a = A()
        b = B()
        c = C()
        d = D()

        a._put_meta("toto", "A")
        a._put_meta("foo", "B")
        b._put_meta("tata", "C")
        b._put_meta("bar", "D")
        c._put_meta("biz", "C")
        c._put_meta("booz", "D")
        d._put_meta("toto", "E")
        d._put_meta("fez", "F")

        self.check_meta(a.get_meta("foo"), [M("foo", "1"), M("foo", "B")])
        self.check_meta(a.get_meta("bar"), [M("bar", "2", "int")])
        self.assertEqual(a.get_meta("biz"), [])
        self.assertEqual(a.get_meta("booz"), [])
        self.assertEqual(a.get_meta("fez"), [])
        self.assertEqual(a.get_meta("spam"), [])
        self.check_meta(a.get_meta("toto"), [M("toto", "A")])
        self.assertEqual(a.get_meta("tata"), [])

        self.check_meta(b.get_meta("foo"),
                        [M("foo", "1"), M("foo", "3")])
        self.check_meta(b.get_meta("bar"),
                        [M("bar", "2", "int"), M("bar", "D")])
        self.check_meta(b.get_meta("biz"), [M("biz", "4")])
        self.assertEqual(b.get_meta("booz"), [])
        self.assertEqual(b.get_meta("fez"), [])
        self.assertEqual(b.get_meta("spam"), [])
        self.assertEqual(b.get_meta("toto"), [])
        self.check_meta(b.get_meta("tata"), [M("tata", "C")])

        self.check_meta(c.get_meta("foo"), [M("foo", "1")])
        self.check_meta(c.get_meta("bar"),
                        [M("bar", "2", "int"), M("bar", "6")])
        self.check_meta(c.get_meta("biz"), [M("biz", "C")])
        self.check_meta(c.get_meta("booz"), [M("booz", "5"), M("booz", "D")])
        self.assertEqual(c.get_meta("fez"), [])
        self.assertEqual(c.get_meta("spam"), [])
        self.assertEqual(c.get_meta("toto"), [])
        self.assertEqual(c.get_meta("tata"), [])

        self.check_meta(d.get_meta("foo"),
                        [M("foo", "1"), M("foo", "8", "num")])
        self.check_meta(d.get_meta("bar"),
                        [M("bar", "2", "int"), M("bar", "6")])
        self.assertEqual(d.get_meta("biz"), [])
        self.check_meta(d.get_meta("booz"), [M("booz", "5"), M("booz", "7")])
        self.check_meta(d.get_meta("fez"), [M("fez", "9"), M("fez", "F")])
        self.assertEqual(d.get_meta("spam"), [])
        self.check_meta(d.get_meta("toto"), [M("toto", "E")])
        self.assertEqual(d.get_meta("tata"), [])

        self.assertEqual(set(a.iter_meta()),
                         set([M("foo", "1"), M("bar", "2", "int"),
                              M("toto", "A"), M("foo", "B")]))
        self.assertEqual(set(b.iter_meta()),
                         set([M("foo", "1"), M("bar", "2", "int"),
                              M("foo", "3"), M("biz", "4"),
                              M("tata", "C"), M("bar", "D")]))
        self.assertEqual(set(c.iter_meta()),
                         set([M("foo", "1"), M("bar", "2", "int"),
                              M("bar", "6"), M("booz", "5"),
                              M("biz", "C"), M("booz", "D")]))
        self.assertEqual(set(d.iter_meta()),
                         set([M("foo", "1"), M("bar", "2", "int"),
                              M("bar", "6"), M("booz", "5"),
                              M("booz", "7"), M("foo", "8", "num"),
                              M("fez", "9"), M("toto", "E"),
                              M("fez", "F")]))

        self.assertEqual(set(a.iter_meta_names()),
                         set(["foo", "bar", "toto"]))
        self.assertEqual(set(b.iter_meta_names()),
                         set(["foo", "bar", "biz", "tata"]))
        self.assertEqual(set(c.iter_meta_names()),
                         set(["foo", "bar", "booz", "biz"]))
        self.assertEqual(set(d.iter_meta_names()),
                         set(["foo", "bar", "booz", "fez", "toto"]))

        self.assertEqual(set(a.iter_meta("spam")), set())
        self.assertEqual(set(b.iter_meta("spam")), set())
        self.assertEqual(set(c.iter_meta("spam")), set())
        self.assertEqual(set(d.iter_meta("spam")), set())

        self.assertEqual(set(a.iter_meta("foo")),
                         set([M("foo", "1"), M("foo", "B")]))
        self.assertEqual(set(b.iter_meta(u"foo")),
                         set([M("foo", "1"), M("foo", "3")]))
        self.assertEqual(set(c.iter_meta("foo")),
                         set([M("foo", "1")]))
        self.assertEqual(set(d.iter_meta(u"foo")),
                         set([M("foo", "1"), M("foo", "8", "num")]))

        self.assertEqual(set(a.iter_meta("bar")),
                         set([M("bar", "2", "int")]))
        self.assertEqual(set(b.iter_meta(u"bar")),
                         set([M("bar", "2", "int"), M("bar", "D")]))
        self.assertEqual(set(c.iter_meta("bar")),
                         set([M("bar", "2", "int"), M("bar", "6")]))
        self.assertEqual(set(d.iter_meta(u"bar")),
                         set([M("bar", "2", "int"), M("bar", "6")]))

        self.assertEqual(set(a.iter_meta("booz")),
                         set([]))
        self.assertEqual(set(b.iter_meta(u"booz")),
                         set([]))
        self.assertEqual(set(c.iter_meta("booz")),
                         set([M("booz", "5"), M("booz", "D")]))
        self.assertEqual(set(d.iter_meta(u"booz")),
                         set([M("booz", "5"), M("booz", "7")]))

        self.assertEqual(set(a.iter_meta("foo", "booz", "spam", "toto")),
                         set([M("foo", "1"), M("toto", "A"), M("foo", "B")]))
        self.assertEqual(set(b.iter_meta("foo", "booz", "spam", "toto")),
                         set([M("foo", "1"), M("foo", "3")]))
        self.assertEqual(set(c.iter_meta("foo", "booz", "spam", "toto")),
                         set([M("foo", "1"), M("booz", "5"), M("booz", "D")]))
        self.assertEqual(set(d.iter_meta("foo", "booz", "spam", "toto")),
                         set([M("foo", "1"), M("booz", "5"),
                              M("booz", "7"), M("foo", "8", "num"),
                              M("toto", "E")]))