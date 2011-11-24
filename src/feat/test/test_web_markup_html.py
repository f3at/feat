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
from feat.web.markup import html

from feat.web.markup.interface import *


class TestHTMLMarkup(common.TestCase):

    @defer.inlineCallbacks
    def testStrictPolicy(self):
        t = html.tags
        e = t.html()(t.HEAD()(t.title()("spam")),
                     (t.BODY()("pim", t.br(), "pam")))
        s = yield e.as_string()
        self.assertEqual(s, '<html><head><title>spam</title></head>'
                         '<body>pim<br>pam</body></html>')

        p = html.StrictPolicy()
        d = html.Document(p, title="Some Title")
        ul = d.ul(class_="test")
        li = d.li()
        d.BR()
        d.div().close()
        li.close()
        ul.close()
        s = yield d.as_string()
        self.assertEqual(s, '<!DOCTYPE HTML PUBLIC \'-//W3C//DTD HTML '
                         '4.01//EN\' '
                         '\'http://www.w3.org/TR/html4/strict.dtd\'>\n'
                         '<html><head><title>Some Title</title></head>'
                         '<body><ul class="test">'
                         '<li><br><div></div></li></ul></body></html>')

        # ensure there is only one html, herad and body tag
        self.assertTrue(d.html is d.html)
        self.assertTrue(d.html() is d.html())
        self.assertTrue(d.html()() is d.html()())
        self.assertTrue(d.head is d.head)
        self.assertTrue(d.head() is d.head())
        self.assertTrue(d.head()() is d.head()())
        self.assertTrue(d.body is d.body)
        self.assertTrue(d.body() is d.body())
        self.assertTrue(d.body()() is d.body()())

        d.body.content.append(t.div())
        s = yield d.as_string()
        self.assertEqual(s, '<!DOCTYPE HTML PUBLIC \'-//W3C//DTD HTML '
                         '4.01//EN\' '
                         '\'http://www.w3.org/TR/html4/strict.dtd\'>\n'
                         '<html><head><title>Some Title</title></head>'
                         '<body><ul class="test">'
                         '<li><br><div></div></li></ul>'
                         '<div></div></body></html>')

        self.assertRaises(html.DeprecatedElement, t.__getattr__, "font")
        self.assertRaises(html.DeprecatedElement, t.__getattr__, "FONT")
        self.assertRaises(html.InvalidElement, t.__getattr__, "spam")
        self.assertRaises(html.InvalidElement, t.__getattr__, "SPAM")

    @defer.inlineCallbacks
    def testLoosePolicy(self):
        t = html.loose_tags
        e = t.html()(t.HEAD()(t.title()("spam")),
                     (t.BODY()("pim", t.basefont(), "pam")))
        s = yield e.as_string()
        self.assertEqual(s, '<html><HEAD><title>spam</title></HEAD>'
                         '<BODY>pim<basefont>pam</BODY></html>')

        p = html.LoosePolicy()
        d = html.Document(p, title="Some Title")
        ul = d.ul(class_="test")
        li = d.li()
        d.BR()
        d.font().close()
        li.close()
        ul.close()
        s = yield d.as_string()
        self.assertEqual(s, '<!DOCTYPE HTML PUBLIC \'-//W3C//DTD HTML 4.01 '
                         'Transitional//EN\' '
                         '\'http://www.w3.org/TR/html4/loose.dtd\'>\n'
                         '<html><head><title>Some Title</title></head>'
                         '<body><ul class="test">'
                         '<li><BR><font></font></li></ul></body></html>')

        # ensure there is only one html, herad and body tag
        self.assertTrue(d.html is d.html)
        self.assertTrue(d.html() is d.html())
        self.assertTrue(d.html()() is d.html()())
        self.assertTrue(d.head is d.head)
        self.assertTrue(d.head() is d.head())
        self.assertTrue(d.head()() is d.head()())
        self.assertTrue(d.body is d.body)
        self.assertTrue(d.body() is d.body())
        self.assertTrue(d.body()() is d.body()())

        d.body.content.append(t.div())
        s = yield d.as_string()
        self.assertEqual(s, '<!DOCTYPE HTML PUBLIC \'-//W3C//DTD HTML 4.01 '
                         'Transitional//EN\' '
                         '\'http://www.w3.org/TR/html4/loose.dtd\'>\n'
                         '<html><head><title>Some Title</title></head>'
                         '<body><ul class="test">'
                         '<li><BR><font></font></li></ul>'
                         '<div></div></body></html>')

        self.assertRaises(html.InvalidElement, t.__getattr__, "spam")
        self.assertRaises(html.InvalidElement, t.__getattr__, "SPAM")
