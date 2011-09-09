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

from feat.web import http


class TestHTTP(common.TestCase):

    def testjoinLocations(self):

        def check(expected, *locations):
            self.assertEqual(expected, http.join_locations(*locations))

        check(None)
        check("", "")
        check("", "", "")
        check("/", "/", "")
        check("/", "/", "/")
        check("foo/bar", "foo", "bar")
        check("foo/bar", "foo/", "bar")
        check("foo/bar", "foo", "/bar")
        check("foo/bar", "foo/", "/bar")
        check("foo/bar/toto/tata", "foo", "bar", "toto", "tata")
        check("foo/bar/toto/tata", "foo/", "/bar/", "/toto/", "/tata")

    def testMime2tuple(self):

        def check(mime, expected):
            result = http.mime2tuple(mime)
            self.assertEqual(result, expected)

        check("", ("*", "*"))
        check("text/html", ("text", "html"))
        check("text", ("text", "*"))
        check("*/*", ("*", "*"))
        check("text/*", ("text", "*"))
        check("*/html", ("*", "html"))
        check("text/html/toto", ("text", "html/toto"))
        check("text/html/*", ("text", "html/*"))

        check("teXt/htML", ("text", "html"))
        check("tEXt", ("text", "*"))
        check("*/*", ("*", "*"))
        check("TEXT/*", ("text", "*"))
        check("*/HTML", ("*", "html"))
        check("teXT/html/Toto", ("text", "html/toto"))

    def testTuply2Mime(self):

        def check(tuple, expected):
            result = http.tuple2mime(tuple)
            self.assertEqual(result, expected)

        check((), "*/*")
        check(("text", ), "text/*")
        check(("text", "html"), "text/html")
        check(("text", "html", "toto"), "text/html/toto")

        check(("teXt", ), "text/*")
        check(("text", "HTML"), "text/html")
        check(("TEXT", "html", "Toto"), "text/html/toto")

    def testSplitDef(self):

        def check(val, expected):
            result = http._split_http_definition(val)
            self.assertEqual(result, expected)

        check(None, (None, {}))
        check("", (None, {}))
        check("text", ("text", {}))
        check("text/html", ("text/html", {}))
        check("*/*", ("*/*", {}))
        check("text; spam=8; bacon=beans",
              ("text", {"spam": "8", "bacon": "beans"}))
        check("   text   ;    spam   =   8   ;    bacon   =   beans   ",
              ("text", {"spam": "8", "bacon": "beans"}))
        check("text; spam=a=b=c; bacon=",
              ("text", {"spam": "a=b=c", "bacon": ""}))

    def testParseContentType(self):

        def check(ct, expected):
            result = http.parse_content_type(ct)
            self.assertEqual(result, expected)

        check("text",
              ("text", http.DEFAULT_ENCODING))
        check("text/html",
              ("text/html", http.DEFAULT_ENCODING))
        check("text/html; q=8",
              ("text/html", http.DEFAULT_ENCODING))
        check("text/html; charset=unicode-1-1-utf-8",
              ("text/html", "utf8"))
        check("text/html; charset=unicode-1-1-utf-8; q=8",
              ("text/html", "utf8"))
        check("text/html; q=8; charset=iso-8859-3",
              ("text/html", "iso-8859-3"))

    def testParseAcceptElement(self):

        def check(val, expected):
            result = http.parse_accepted_type(val)
            self.assertEqual(result, expected)

        check("text", ("text", http.DEFAULT_PRIORITY))
        check("text/html", ("text/html", http.DEFAULT_PRIORITY))
        check("text/html; charset=unicode-1-1-utf-8",
              ("text/html", http.DEFAULT_PRIORITY))
        check("text/html; q=0.42", ("text/html", 0.42))
        check("text/html; charset=unicode-1-1-utf-8; q=0.33",
              ("text/html", 0.33))
        check("text/html; q=0; charset=iso-8859-3", ("text/html", 0))

    def testParseAcceptCharsetElement(self):

        def check(val, expected):
            result = http.parse_accepted_charset(val)
            self.assertEqual(result, expected)

        check("iso-8859-3", ("iso-8859-3", http.DEFAULT_PRIORITY))
        check("unicode-1-1-utf-8", ("utf8", http.DEFAULT_PRIORITY))
        check("iso-8859-1; q=0.18", ("iso-8859-1", 0.18))

    def testParseAccept(self):

        def check(val, expected):
            result = http.parse_accepted_types(val)
            self.assertEqual(result, expected)

        check("text/html, text/*, */*",
              {"text/html": http.DEFAULT_PRIORITY,
               "text/*": http.DEFAULT_PRIORITY,
               "*/*": http.DEFAULT_PRIORITY})
        check("text/html, text/*, */*; q=0.42",
              {"text/html": http.DEFAULT_PRIORITY,
               "text/*": http.DEFAULT_PRIORITY,
               "*/*": 0.42})
        check("text/html; q=0.9, text/*, */*; q=0.42",
              {"text/html": 0.9,
               "text/*": http.DEFAULT_PRIORITY,
               "*/*": 0.42})

        check("text/html; q=0.9, text/*; q=0.18, */*; q=0.42",
              {"text/html": 0.9,
               "text/*": 0.18,
               "*/*": 0.42})

    def testParseAcceptLanguage(self):

        def check(val, expected):
            result = http.parse_accepted_languages(val)
            self.assertEqual(result, expected)

        check("en, fr, *",
              {"en": http.DEFAULT_PRIORITY,
               "fr": http.DEFAULT_PRIORITY,
               "*": http.DEFAULT_PRIORITY})
        check("en, fr, *; q=0.42",
              {"en": http.DEFAULT_PRIORITY,
               "fr": http.DEFAULT_PRIORITY,
               "*": 0.42})
        check("en; q=0.9, fr, *; q=0.42",
              {"en": 0.9,
               "fr": http.DEFAULT_PRIORITY,
               "*": 0.42})
        check("en; q=0.9, fr; q=0.18, *; q=0.42",
              {"en": 0.9,
               "fr": 0.18,
               "*": 0.42})

    def testParseAcceptCharset(self):

        def check(val, expected):
            result = http.parse_accepted_charsets(val)
            self.assertEqual(result, expected)

        check("iso-8859-3, unicode-1-1-utf-8, iso-8859-1",
              {"iso-8859-3": http.DEFAULT_PRIORITY,
               "utf8": http.DEFAULT_PRIORITY,
               "iso-8859-1": http.DEFAULT_PRIORITY})
        check("iso-8859-3, unicode-1-1-utf-8; q=0.46, iso-8859-1",
              {"iso-8859-3": http.DEFAULT_PRIORITY,
               "utf8": 0.46,
               "iso-8859-1": http.DEFAULT_PRIORITY})
        check("iso-8859-3; q=0.88, unicode-1-1-utf-8;q=0.78, iso-8859-1",
              {"iso-8859-3": 0.88,
               "utf8": 0.78,
               "iso-8859-1": http.DEFAULT_PRIORITY})

    def testTuple2Path(self):

        def check(tup, expected):
            result = http.tuple2path(tup)
            self.assertEqual(result, expected)

        check((), "")
        check(("", ), "")
        check(("test", ), "test")
        check(("test", "toto"), "test/toto")
        check(("test", "toto", ""), "test/toto/")
        check(("", "test", ), "/test")
        check(("", "test", "toto"), "/test/toto")
        check(("", "test", "toto", ""), "/test/toto/")

    def testPath2Tuple(self):

        def check(path, expected):
            result = http.path2tuple(path)
            self.assertEqual(result, expected)

        check("", ("", ))
        check("/", ("", ""))
        check("/test", ("", "test"))
        check("/test/toto", ("", "test", "toto"))
        check("/test/toto/", ("", "test", "toto", ""))
        check("test", ("test", ))
        check("test/toto", ("test", "toto"))
        check("test/toto/", ("test", "toto", ""))

    def testUnicode(self):

        def t2p(tup, expected, encoding="utf8"):
            result = http.tuple2path(tup, encoding=encoding)
            self.assertEqual(result, expected)

        t2p(("test", u"パス名", "url", ),
            "test/%E3%83%91%E3%82%B9%E5%90%8D/url")
        t2p(("test", u"パス名", "url", ),
            "test/%C7i%C7Q%A6W/url", "big5")
        t2p(("t<e\"st", u"パス名", "u>r/l", ),
            "t%3Ce%22st/%C7i%C7Q%A6W/u%3Er%2Fl", "big5")

    def testPingPong(self):

        def check(tup, encoding="utf8"):
            inter = http.tuple2path(tup, encoding=encoding)
            result = http.path2tuple(inter, encoding=encoding)
            self.assertEqual(result, tup)

        check(('', ))
        check((u'', ), "iso-8859-1")

        check(('test', ))
        check((u'test', ), "iso-8859-1")

        check((u'tëst', ))
        check((u'tëst', ), "iso-8859-1")

        check((u"パス名", "pim", "\"'<>", ""))
        check((u"パス名", "pim", "\"'<>", ""), "big5")

        check(("", )*10)
