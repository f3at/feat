# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

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

from feat.test import common

from feat.common import defer, time
from feat.web.markup import base

from feat.web.markup.interface import *


class TestPolicy(base.BasePolicy):

    def is_leaf(self, tag):
        return tag in ("leaf", "no_closing", "require_closing_leaf")

    def needs_no_closing(self, tag):
        return tag == "no_closing"

    def is_self_closing(self, tag):
        return tag not in ("require_closing_node", "require_closing_leaf")

    def resolve_attr_error(self, failure):
        return "%s: %s" % (failure.type.__name__, failure.getErrorMessage())

    def resolve_content_error(self, failure):
        error = base.Element("error", self)(type=failure.type.__name__)
        error.append(failure.getErrorMessage())
        return error


class TestBaseMarkup(common.TestCase):

    @defer.inlineCallbacks
    def testEscaping(self):
        policy = base.BasePolicy()
        tag = base.ElementBuilder(policy)

        e = tag.A(test="<>&'\"")("<>&'\"")
        yield self.asyncEqual('<a test="&lt;&gt;&amp;\'&quot;">'
                              '&lt;&gt;&amp;\'"</a>',
                              e.as_string())

    @defer.inlineCallbacks
    def testForwardedAsyncErrors(self):

        def fail(delay, error_class, *args, **kwargs):

            def raise_error(_param):
                raise error_class(*args, **kwargs)

            d = defer.Deferred()
            d.addCallback(raise_error)
            time.call_later(delay, d.callback, None)
            return d

        policy = base.BasePolicy()
        tag = base.ElementBuilder(policy)

        fa = fail(0.01, KeyError, "toto")
        e = tag.A(attr=fa)()
        yield self.asyncErrback(KeyError, e.__getitem__, "attr")
        yield self.asyncErrback(KeyError, e.as_string)

        fv = fail(0.01, ValueError, "tata")
        e = tag.A()(fv)
        yield self.asyncErrback(ValueError, e.content.__getitem__, 0)
        yield self.asyncErrback(ValueError, e.as_string)

        e = tag.A(attr=fa)(fv)
        yield self.asyncErrback(KeyError, e.__getitem__, "attr")
        yield self.asyncErrback(ValueError, e.content.__getitem__, 0)
        yield self.asyncErrback(KeyError, e.as_string)

        self.assertFailure(fa, KeyError)
        self.assertFailure(fv, ValueError)

    @defer.inlineCallbacks
    def testResolvedAsyncErrors(self):

        def fail(delay, error_class, *args, **kwargs):

            def raise_error(_param):
                raise error_class(*args, **kwargs)

            d = defer.Deferred()
            d.addCallback(raise_error)
            time.call_later(delay, d.callback, None)
            return d

        policy = TestPolicy()
        tag = base.ElementBuilder(policy)

        fa = fail(0.01, KeyError, "toto")
        fv = fail(0.01, ValueError, "tata")
        e = tag.A(attr=fa)(fv)

        s = yield e.as_string()
        self.assertEqual(s, '<a attr="KeyError: \'toto\'">'
                         '<error type="ValueError">tata</error></a>')

        self.assertTrue(isinstance(e["attr"], defer.Deferred))
        yield self.asyncEqual("KeyError: 'toto'", e["attr"])

        self.assertTrue(isinstance(e.content[0], defer.Deferred))
        error = yield e.content[0]
        self.assertTrue(IElement.providedBy(error))
        self.assertEqual(error.tag, "error")

    def testSyncErrors(self):
        policy = TestPolicy()
        tag = base.ElementBuilder(policy)

        e = tag.toto()()
        self.assertRaises(MarkupError, e.__setitem__, "test", tag.tata())

        self.assertRaises(AttributeError, tag.__getattr__, "__bad__")
        self.assertRaises(AttributeError, tag.__getattr__, "__bad")
        self.assertRaises(MarkupError, tag.toto.close)

        doc = base.Document(policy)

        self.assertRaises(AttributeError, doc.__getattr__, "__bad__")
        self.assertRaises(AttributeError, doc.__getattr__, "__bad")

        t = doc.test()
        t.close()
        self.assertRaises(MarkupError, t.close)

        a = doc.a()
        b = doc.b()
        self.assertRaises(MarkupError, a.close)
        b.close()
        a.close()

    @defer.inlineCallbacks
    def testElement(self):
        policy = base.BasePolicy()
        tag = base.ElementBuilder(policy)

        delay = common.delay
        e = tag.A(a=1, b=delay(2, 0.01))("XX", delay("YY", 0.01), "ZZ")

        self.assertTrue(IElement.providedBy(e))
        self.assertTrue(IElementContent.providedBy(e.content))
        self.assertFalse(e.is_leaf)
        self.assertFalse(e.needs_no_closing)
        self.assertTrue(e.is_self_closing)
        self.assertEqual(e.tag, "a")
        self.assertEqual(len(e), 2)
        self.assertTrue("a" in e)
        self.assertFalse("c" in e)
        self.assertTrue(isinstance(e["a"], unicode))
        self.assertTrue(isinstance(e["b"], defer.Deferred))
        values = yield defer.join(*(list(e)))
        self.assertEqual(set(values), set(["a", "b"]))
        e["c"] = 3
        self.assertEqual(len(e), 3)
        self.assertTrue("a" in e)
        self.assertTrue("c" in e)
        self.assertTrue(isinstance(e["c"], unicode))
        self.assertEqual("1", e["a"])
        yield self.asyncEqual("2", e["b"])
        self.assertEqual("3", e["c"])
        values = yield defer.join(*(list(e)))
        self.assertEqual(set(values), set(["a", "b", "c"]))

    @defer.inlineCallbacks
    def testLeafElement(self):
        policy = TestPolicy()
        tag = base.ElementBuilder(policy)

        c = tag.node(attr=1)
        self.assertTrue(IElementContent.providedBy(c))
        e = c.element
        self.assertFalse(e.is_leaf)
        self.assertFalse(e.needs_no_closing)
        self.assertTrue(e.is_self_closing)
        self.assertTrue(IElement.providedBy(e))

        e = tag.leaf(attr=1)
        self.assertTrue(e.is_leaf)
        self.assertFalse(e.needs_no_closing)
        self.assertTrue(e.is_self_closing)
        self.assertTrue(IElement.providedBy(e))
        self.assertRaises(MarkupError, getattr, e, "content")

        doc = base.Document(policy)
        doc.root()
        doc.node()
        doc.node()
        yield self.asyncEqual('<root><node><node /></node></root>',
                              doc.as_string())

        doc = base.Document(policy)
        doc.root()
        doc.leaf()
        doc.leaf()
        yield self.asyncEqual('<root><leaf /><leaf /></root>', doc.as_string())

        d = lambda v: common.delay(v, 0.01)
        e = tag.A()(tag.leaf(), d(tag.leaf(a=1)), d(tag.leaf()))
        yield self.asyncEqual('<a><leaf /><leaf a="1" /><leaf /></a>',
                              e.as_string())

    @defer.inlineCallbacks
    def testNoClosing(self):
        policy = TestPolicy()
        tag = base.ElementBuilder(policy)

        e = tag.no_closing()
        self.assertTrue(e.is_leaf)
        self.assertTrue(e.needs_no_closing)
        self.assertTrue(IElement.providedBy(e))
        self.assertRaises(MarkupError, getattr, e, "content")
        yield self.asyncEqual('<no_closing>', e.as_string())

        doc = base.Document(policy)
        doc.root()
        doc.no_closing()
        doc.no_closing()
        yield self.asyncEqual('<root><no_closing><no_closing></root>',
                              doc.as_string())

        d = lambda v: common.delay(v, 0.01)
        e = tag.A()(tag.no_closing(),
                    d(tag.no_closing(a=1)),
                    d(tag.no_closing()))
        yield self.asyncEqual('<a><no_closing><no_closing a="1">'
                              '<no_closing></a>', e.as_string())

    @defer.inlineCallbacks
    def testSelfClosing(self):
        policy = TestPolicy()
        tag = base.ElementBuilder(policy)

        e = tag.require_closing_leaf()
        self.assertTrue(IElement.providedBy(e))
        self.assertTrue(e.is_leaf)
        self.assertFalse(e.is_self_closing)
        self.assertRaises(MarkupError, getattr, e, "content")
        yield self.asyncEqual("<require_closing_leaf></require_closing_leaf>",
                              e.as_string())

        e = tag.require_closing_node()
        self.assertTrue(IElementContent.providedBy(e))
        e = e.element
        self.assertTrue(IElement.providedBy(e))
        self.assertFalse(e.is_leaf)
        self.assertFalse(e.is_self_closing)
        self.assertTrue(IElementContent.providedBy(e.content))
        yield self.asyncEqual("<require_closing_node></require_closing_node>",
                              e.as_string())
        e.content.append("XXX")
        yield self.asyncEqual("<require_closing_node>XXX"
                              "</require_closing_node>",
                              e.as_string())

    @defer.inlineCallbacks
    def testElementContent(self):
        policy = base.BasePolicy()
        tag = base.ElementBuilder(policy)

        delay = common.delay
        e = tag.A(a=1, b=delay(2, 0.01))("XX", delay("YY", 0.01), "ZZ")

        self.assertEqual(len(e.content), 3)
        self.assertEqual("XX", e.content[0])
        self.assertTrue(isinstance(e.content[1], defer.Deferred))
        yield self.asyncEqual("YY", e.content[1])
        values = yield defer.join(*(list(e.content)))
        self.assertEqual(set(values), set(["XX", "YY", "ZZ"]))
        e.content.append("OO")
        self.assertEqual(len(e.content), 4)
        self.assertEqual("OO", e.content[3])
        values = yield defer.join(*(list(e.content)))
        self.assertEqual(set(values), set(["XX", "YY", "ZZ", "OO"]))

    @defer.inlineCallbacks
    def testDocumentRendering(self):
        policy = base.BasePolicy()
        tag = base.ElementBuilder(policy)

        doc = base.Document(policy)
        doc.root(attr1=45, attr2="XX")
        doc.sub()("VVV").close()
        doc.sub()(tag.a(), "XXX", tag.b()("ZZZ"))
        doc.c(name="toto")().close().close()
        s = doc.sub()("AAA")
        doc.d().close()
        doc.e().close()
        s.close()

        yield self.asyncEqual('<root attr1="45" attr2="XX">'
                              '<sub>VVV</sub>'
                              '<sub><a />XXX<b>ZZZ</b><c name="toto" /></sub>'
                              '<sub>AAA<d /><e /></sub>'
                              '</root>',
                              doc.as_string())

        delay = common.delay
        doc = base.Document(policy)
        doc.root(attr1=delay(45, 0.01), attr2="XX")
        doc.sub()(delay("VVV", 0.01)).close()
        doc.sub()(tag.a(), "XXX", delay(tag.b()("ZZZ"), 0.02))
        doc.c(name="toto")().close().close()
        s = doc.sub()(delay("AAA", 0.1))
        doc.d().close()
        doc.e().close()
        s.close()

        yield self.asyncEqual('<root attr1="45" attr2="XX">'
                              '<sub>VVV</sub>'
                              '<sub><a />XXX<b>ZZZ</b><c name="toto" /></sub>'
                              '<sub>AAA<d /><e /></sub>'
                              '</root>',
                              doc.as_string())

    @defer.inlineCallbacks
    def testElementRendering(self):

        @defer.inlineCallbacks
        def check(element, expected):
            yield self.asyncEqual(expected, element.as_string())

        policy = base.BasePolicy()
        tag = base.ElementBuilder(policy)
        d = lambda v: common.delay(v, 0.01)

        yield check(tag.TOTO()(), "<toto />")

        yield check(tag.TOTO(test=None)(), "<toto test />")

        yield check(tag.TOTO(test=d(None))(), "<toto test />")

        yield check(tag.PIM()("aaa", "bbb"),
                    "<pim>aaabbb</pim>")

        yield check(tag.PIM()(tag.PAM(), tag.POUM()),
                    "<pim><pam /><poum /></pim>")

        yield check(tag.SPAM(aaa=1, bbb=2, ccc=3)(),
                    "<spam aaa=\"1\" bbb=\"2\" ccc=\"3\" />")

        yield check(tag.SPAM(BACON=42)("toto", tag.EGG(), "tata"),
                    "<spam bacon=\"42\">toto<egg />tata</spam>")

        yield check(tag.TOTO()(common.delay(tag.PIM(), 0.02),
                               11,
                               common.delay(tag.PAM(), 0.01),
                               tag.POUM(),
                               common.delay(22, 0.02)),
                    "<toto><pim />11<pam /><poum />22</toto>")

        yield check(tag.SPAM(aaa=common.delay(1, 0.02),
                             bbb=2,
                             ccc=common.delay(3, 0.01))(),
                    "<spam aaa=\"1\" bbb=\"2\" ccc=\"3\" />")

        yield check(tag.A(a=1, b=2)(tag.B(c=3),
                                    tag.D(d=4)(tag.E()(tag.F(e=5)),
                                               tag.G(h=6))),
                    '<a a="1" b="2"><b c="3" /><d d="4">'
                    '<e><f e="5" /></e><g h="6" /></d></a>')

        # Now everything asynchronous
        yield check(tag.A(a=d(1), b=d(2))
                    (d(tag.B(c=d(3))),
                     d(tag.D(d=d(4))
                       (d(tag.E()
                          (d(tag.F(e=d(5))))),
                        d(tag.G(h=d(6)))))),
                    '<a a="1" b="2"><b c="3" /><d d="4">'
                    '<e><f e="5" /></e><g h="6" /></d></a>')

    @defer.inlineCallbacks
    def testPolicySpeparator(self):

        @defer.inlineCallbacks
        def check(element, expected):
            yield self.asyncEqual(expected, element.as_string())

        policy = base.BasePolicy()
        tag = base.ElementBuilder(policy)
        delay = common.delay

        yield check(tag.TEST()("aaa", "bbb", "ccc"),
                    "<test>aaabbbccc</test>")

        yield check(tag.TEST()(delay("aaa", 0.01), "bbb", delay("ccc", 0.01)),
                    "<test>aaabbbccc</test>")

        policy.content_separator = " "

        yield check(tag.TEST()("aaa", "bbb", "ccc"),
                    "<test>aaa bbb ccc</test>")

        yield check(tag.TEST()(delay("aaa", 0.01), "bbb", delay("ccc", 0.01)),
                    "<test>aaa bbb ccc</test>")
