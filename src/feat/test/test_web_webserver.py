# -*- Mode: Python -*-
# -*- coding: UTF-8 -*-
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
import os
import tempfile
import types

from feat.test import common

from zope.interface import Interface, implements

from StringIO import StringIO

from twisted.internet import address
from twisted.web.server import NOT_DONE_YET
from twisted.web.http import Headers

from feat.common import defer
from feat.web import http, document, webserver, compat, auth


### TestTypeNegociation ###


class IA(Interface):
    pass


class IB(Interface):
    pass


class IC(Interface):
    pass


class ID(Interface):
    pass


class IN(Interface):
    pass


class Dummy(object):

    def __init__(self, value=None):
        self.value = value


class A(Dummy):
    implements(IA)


class B(Dummy):
    implements(IB)


class C(Dummy):
    implements(IC)


class D(Dummy):
    implements(ID)


class Negotiable(object):
    implements(IN, webserver.INegotiable)

    def __init__(self, values, encodings=None, languages=None):
        self.values = values
        self.allowed_encodings = encodings
        self.allowed_languages = languages


@common.attr(timescale=0.2)
class TestTypeNegociation(common.TestCase):

    def setUp(self):
        self.registry = document.Registry()
        self.server = webserver.Server(0, None, registry=self.registry)

    def enable_mime_type(self, mime_type, priority):
        self.server.enable_mime_type(mime_type, priority)

    def register_dummy_writer(self, mime_type, iface):

        def dummy_writer(doc, obj):
            self.fail("Should not be called")

        self.registry.register_writer(dummy_writer, mime_type, iface)

    def testNegotiateMimeTypesWithoutAccept(self):

        def check(obj, expected):
            types = self.server.negotiate_mime_types(obj)
            type = (types and types[0]) or None
            self.assertEqual(type, expected)

        a = A()
        b = B()
        c = C()

        self.enable_mime_type("text/html", 0.8)
        self.enable_mime_type("text/xml", 0.5)
        self.enable_mime_type("text/plain", 0.2)

        check(a, None)
        check(b, None)
        check(c, None)

        self.register_dummy_writer("text/plain", IA)

        check(a, "text/plain")
        check(b, None)
        check(c, None)

        self.register_dummy_writer("text/xml", IA)
        self.register_dummy_writer("text/plain", IB)

        check(a, "text/xml")
        check(b, "text/plain")
        check(c, None)

        self.register_dummy_writer("text/html", IA)
        self.register_dummy_writer("text/xml", IB)
        self.register_dummy_writer("text/plain", IC)

        check(a, "text/html")
        check(b, "text/xml")
        check(c, "text/plain")

        self.register_dummy_writer("text/html", IB)
        self.register_dummy_writer("text/xml", IC)

        check(a, "text/html")
        check(b, "text/html")
        check(c, "text/xml")

        self.register_dummy_writer("text/html", IC)

        check(a, "text/html")
        check(b, "text/html")
        check(c, "text/html")

    def testNegotiateMimeTypesWithAccept(self):

        def check(obj, expected, accept):
            types = self.server.negotiate_mime_types(obj, accept)
            type = (types and types[0]) or None
            self.assertEqual(type, expected)

        a = A()


        self.enable_mime_type("text/html", 0.6)
        self.enable_mime_type("text/xml", 0.5)
        self.enable_mime_type("text/plain", 0.4)

        check(a, None, {})
        check(a, None, {"text/html": 1.0, "text/xml": 1.0, "text/plain": 1.0})
        check(a, None, {"*/html": 1.0, "text/*": 1.0, "*/*": 1.0})
        check(a, None, {"spam/bacon": 1.0, "test": 1.0})

        self.register_dummy_writer("text/xml", IA)

        check(a, "text/xml", {})
        check(a, "text/xml", {"text/xml": 0.1})
        check(a, "text/xml", {"text/html": 1.0, "text/plain": 1.0})
        check(a, "text/xml", {"*/*": 0.0})

        self.register_dummy_writer("text/plain", IA)

        check(a, "text/xml", {})
        check(a, "text/xml", {"text/xml": 0.1})
        check(a, "text/xml", {"text/plain": 0.0})
        check(a, "text/plain", {"text/plain": 0.1})
        check(a, "text/plain", {"text/xml": 0.1, "text/plain": 0.5})
        check(a, "text/xml", {"text/xml": 0.1, "text/plain": 0.1})
        check(a, "text/xml", {"text/*": 0.1})
        check(a, "text/xml", {"*/*": 0.1})
        check(a, "text/plain", {"text/xml": 0.1, "text/*": 0.3})
        check(a, "text/xml", {"text/html": 0.1, "*/*": 0.2})
        check(a, "text/plain", {"text/html": 0.2, "text/plain": 0.1})
        check(a, "text/xml", {"text/html": 0.3, "text/*": 0.1})
        check(a, "text/xml", {"text/html": 0.3, "text/xml": 0.2, "*/*": 0.1})
        check(a, "text/plain", {"text/xml": 0.0, "*/*": 1.0})
        check(a, "text/plain", {"text/plain": 1.0, "*/*": 0.0})

        self.register_dummy_writer("text/html", IA)

        check(a, "text/html", {})
        check(a, "text/xml", {"text/xml": 0.1})
        check(a, "text/plain", {"text/plain": 0.1})
        check(a, "text/plain", {"text/html": 0.1, "text/xml": 0.2,
                                "text/plain": 0.3})
        check(a, "text/html", {"text/html": 0.1, "text/xml": 0.1,
                               "text/plain": 0.1})
        check(a, "text/plain", {"text/*": 0.1, "text/plain": 0.5})
        check(a, "text/html", {"text/*": 0.1, "text/plain": 0.1})
        check(a, "text/html", {"text/*": 0.5, "text/plain": 0.1})

    def testNegotiateForcedAspect(self):

        def check(valid, accept, expected):
            types = self.server.negotiate_forced_aspect(valid, accept)
            type = (types and types[0]) or None
            self.assertEqual(type, expected)

        check((), {}, None)
        check(None, {}, None)
        check((), None, None)
        check(None, None, None)

        check(("a", "b", "c"), {}, None)
        check(("a", "b", "c"), {"*": 0.5}, "a")
        check(("a", "b", "c"), {"b": 0.5}, "b")
        check(("a", "b", "c"), {"1": 0.5}, None)
        check(("a", "b", "c"), {"1": 0.5, "*": 0.0}, "a")
        check(("a", "b", "c"), {"a": 0.1, "b": 0.2, "c": 0.3}, "c")
        check(("a", "b", "c"), {"a": 0.1, "b": 0.2, "c": 0.2}, "b")
        check(("a", "b", "c"), {"a": 0.1, "b": 0.1, "c": 0.1}, "a")


### TestResourceWrapper ###


class DummyPrivateChannel(object):

    def __init__(self):
        self.transport = None


class DummyPrivateRequest(object):

    def __init__(self, uri="/"):
        self.code = None
        self.method = "GET"
        self.clientproto = "HTTP/1.0"
        self.path = uri
        self.uri = uri
        self.client = address.IPv4Address("TCP", "127.0.0.1", 12345)
        self.host = address.IPv4Address("TCP", "127.0.0.2", 12345)
        self.content = StringIO()
        self.request_headers = {}
        self.responseHeaders = Headers()
        self._finished = defer.Deferred()
        self.channel = DummyPrivateChannel()

    def setResponseCode(self, code):
        self.code = code

    def finish(self):
        self._finished.callback(self)

    def getHeader(self, name):
        return self.request_headers.get(name.lower(), None)

    def setHeader(self, name, value):
        self.responseHeaders.setRawHeaders(name, [value])

    @property
    def response_headers(self):
        return dict((k.lower(), v[0])
                    for k, v in self.responseHeaders.getAllRawHeaders())

    @response_headers.setter
    def flush_response_headers(self, value):
        assert value == dict(), repr(value)
        self.responseHeaders = Headers()

    def write(self, data):
        self.content.write(data)

    def notifyFinish(self):
        d = defer.Deferred()
        self._finished.addCallback(defer.drop_param, d.callback, self)
        return d


class DelayableMixin(object):

    def call(self, delay, fun, *args, **kwargs):
        if isinstance(delay, types.GeneratorType):
            delay = delay.next()

        if delay is None:
            return fun(*args, **kwargs)

        d = common.delay(None, delay)
        d.addCallback(defer.drop_param, fun, *args, **kwargs)
        return d


class DummyResource(webserver.BasicResource, DelayableMixin):

    def __init__(self,
                 authenticator=None, authorizer=None,
                 locate_error=None, locate_delay=None,
                 render_status=None, render_content=None,
                 render_error=None, render_delay=None,
                 error_status=None, error_content=None,
                 error_error=None, error_delay=None):
        webserver.BasicResource.__init__(self, authenticator, authorizer)

        self._locate_error = locate_error
        self._locate_delay = locate_delay
        self._render_status = render_status
        self._render_content = render_content
        self._render_error = render_error
        self._render_delay = render_delay
        self._error_status = error_status
        self._error_content = error_content
        self._error_error = error_error
        self._error_delay = error_delay

    def locate_resource(self, request, location, remaining):
        return self.call(self._locate_delay, self.do_locate_resource,
                         request, location, remaining)

    def render_resource(self, request, response, location):
        return self.call(self._render_delay, self.do_render_resource,
                         request, response, location)

    def render_error(self, request, response, error):
        return self.call(self._error_delay, self.do_render_error,
                         request, response, error)

    def do_locate_resource(self, req, loc, rem):
        if self._locate_error is not None:
            raise self._locate_error
        return webserver.BasicResource.locate_resource(self, req, loc, rem)

    def do_render_resource(self, request, response, location):
        if self._render_status is not None:
            response.set_status(self._render_status)
        if self._render_error is not None:
            raise self._render_error
        return self._render_content

    def do_render_error(self, request, response, error):
        if self._error_status is not None:
            response.set_status(self._error_status)
        if self._error_error is not None:
            raise self._error_error
        if self._error_content:
            return self._error_content
        # By default we don't handle the error rendering
        raise error


class DummyAuthenticator(auth.BasicAuthenticator, DelayableMixin):

    def __init__(self, realm, users, auth_delay=None):
        auth.BasicAuthenticator.__init__(self, realm, users)
        self._auth_delay = auth_delay

    def authenticate(self, request, credentials, location):
        return self.call(self._auth_delay,
                         auth.BasicAuthenticator.authenticate,
                         self, request, credentials, location)


class DummyAuthorizer(DelayableMixin):

    implements(auth.IAuthorizer)

    def __init__(self, locations, auth_delay=None):
        self._locations = set([http.path2tuple(v) if isinstance(v, str) else v
                               for v in locations])
        self._auth_delay = auth_delay

    def authorize(self, request, credentials, location):
        return self.call(self._auth_delay, self.do_authorize,
                         request, credentials, location)

    def do_authorize(self, request, credentials, location):
        return location in self._locations


def delay_generator():
    while True:
        yield None
        yield 0

delay_gen = delay_generator()


TEXT_PLAIN = "text/plain"
TEXT_UPPER = "text/uppercase"
TEXT_LOWER = "text/lowercase"


@common.attr(timescale=0.2)
class TestWebServer(common.TestCase):

    configurable_attributes = common.TestCase.configurable_attributes \
                              + ["locate_delay", "render_delay",
                                 "error_delay", "authen_delay",
                                 "author_delay"]

    locate_delay = None
    render_delay = None
    error_delay = None
    authen_delay = None
    author_delay = None

    def check(self, uri="/",
              mime_types=None, encodings=None, languages=None,
              credentials=None,
              is_async=None, status=None, content=None,
              mime=None, encoding=None, language=None,
              allowed_encodings=None, allowed_languages=None,
              allowed_methods=None, www_auth=None,
              location=None):

        def not_expected(failure):
            self.fail("Request should not fail")

        def check_expected(request):
            if status is not None:
                self.assertEqual(request.code, status)
            if content is not None:
                self.assertEqual(request.content.getvalue(), content)
            if (mime is not None) or (encoding is not None):
                content_type = http.DEFAULT_MIMETYPE
                charset = compat.http2python(http.DEFAULT_ENCODING)
                if "content-type" in request.response_headers:
                    header = request.response_headers["content-type"]
                    content_type, charset = http.parse_content_type(header)
                if mime is not None:
                    self.assertEqual(content_type, mime)
                if encoding is not None:
                    self.assertEqual(charset, encoding)
            if language is not None:
                content_language = http.DEFAULT_LANGUAGE
                if "content-language" in request.response_headers:
                    header = request.response_headers["content-language"]
                    content_language = header
                self.assertEqual(content_language, language)
            if allowed_encodings is not None:
                self.assertTrue("allow-charset" in request.response_headers)
                header = request.response_headers["allow-charset"]
                values = [e.strip() for e in header.split(",")]
                self.assertEqual(tuple(values), allowed_encodings)
            if allowed_languages is not None:
                self.assertTrue("allow-language" in request.response_headers)
                header = request.response_headers["allow-language"]
                values = [e.strip() for e in header.split(",")]
                self.assertEqual(tuple(values), allowed_languages)
            if allowed_methods is not None:
                self.assertTrue("allow" in request.response_headers)
                header = request.response_headers["allow"]
                values = [e.strip() for e in header.split(",")]
                self.assertEqual(tuple(values), allowed_methods)
            if www_auth is not None:
                self.assertTrue("www-authenticate" in request.response_headers)
                header = request.response_headers["www-authenticate"]
                self.assertEqual(header, www_auth)
            if location is not None:
                self.assertTrue("location" in request.response_headers)
                header = request.response_headers["location"]
                self.assertEqual(header, location)

        request = DummyPrivateRequest(uri)

        if mime_types is not None:
            request.request_headers["accept"] = mime_types
        else:
            request.request_headers["accept"] = "*"

        if encodings is not None:
            request.request_headers["accept-charset"] = encodings
        else:
            request.request_headers["accept-charset"] = "*"

        if languages is not None:
            request.request_headers["accept-languages"] = languages
        else:
            request.request_headers["accept-languages"] = "*"

        if credentials is not None:
            request.request_headers["authorization"] = credentials.header_value

        result = self.server._process_request(request)

        self.assertEqual(result, NOT_DONE_YET)

        d = request.notifyFinish()
        d.addCallbacks(check_expected, not_expected)
        return d

    def check_sync(self, uri, status, content, **kwargs):
        return self.check(uri, is_async=False, status=status,
                          content=content, **kwargs)

    def check_async(self, uri, status, content, **kwargs):
        return self.check(uri, is_async=True, status=status,
                          content=content, **kwargs)

    def check_any(self, uri, status, content, **kwargs):
        return self.check(uri, status=status, content=content, **kwargs)

    @defer.inlineCallbacks
    def testSyncLocateSyncRender(self):
        yield self.check_good_values(self.check_sync)
        yield self.check_not_found(self.check_sync)
        yield self.check_moved(self.check_sync)
        yield self.check_errors(self.check_sync)
        yield self.check_authentication(self.check_sync)
        yield self.check_authentication_errors(self.check_sync)
        yield self.check_authorization(self.check_sync)
        yield self.check_authorization_errors(self.check_sync)

    @common.attr(authen_delay=0)
    @defer.inlineCallbacks
    def testAsyncAuthenticate(self):
        yield self.check_authentication(self.check_async)
        yield self.check_authentication_errors(self.check_async)

    @common.attr(author_delay=0)
    @defer.inlineCallbacks
    def testAsyncAuthorization(self):
        yield self.check_authorization(self.check_async)
        yield self.check_authorization_errors(self.check_async)

    @common.attr(authen_delay=0, author_delay=0)
    @defer.inlineCallbacks
    def testAsyncAuth(self):
        yield self.check_authentication(self.check_async)
        yield self.check_authentication_errors(self.check_async)
        yield self.check_authorization(self.check_async)
        yield self.check_authorization_errors(self.check_async)

    @common.attr(render_delay=0)
    @defer.inlineCallbacks
    def testSyncLocateAsyncRender(self):
        yield self.check_good_values(self.check_async)
        yield self.check_not_found(self.check_sync)
        yield self.check_moved(self.check_sync)
        yield self.check_errors(self.check_async)
        yield self.check_authentication(self.check_async)
        yield self.check_authentication_errors(self.check_sync)
        yield self.check_authorization(self.check_async)
        yield self.check_authorization_errors(self.check_sync)

    @common.attr(locate_delay=0)
    @defer.inlineCallbacks
    def testAsyncLocateSyncRender(self):
        yield self.check_good_values(self.check_async)
        yield self.check_not_found(self.check_async)
        yield self.check_moved(self.check_async)
        yield self.check_errors(self.check_async)
        yield self.check_authentication(self.check_async)
        yield self.check_authentication_errors(self.check_async)
        yield self.check_authorization(self.check_async)
        yield self.check_authorization_errors(self.check_async)

    @common.attr(locate_delay=0, render_delay=0)
    @defer.inlineCallbacks
    def testAsyncLocateAsyncRender(self):
        yield self.check_good_values(self.check_async)
        yield self.check_not_found(self.check_async)
        yield self.check_moved(self.check_async)
        yield self.check_errors(self.check_async)
        yield self.check_authentication(self.check_async)
        yield self.check_authentication_errors(self.check_async)
        yield self.check_authorization(self.check_async)
        yield self.check_authorization_errors(self.check_async)

    @common.attr(locate_delay=0, render_delay=0, error_delay=0, authen_delay=0)
    @defer.inlineCallbacks
    def testFullAsync(self):
        yield self.check_good_values(self.check_async)
        yield self.check_not_found(self.check_async)
        yield self.check_moved(self.check_async)
        yield self.check_errors(self.check_async)
        yield self.check_authentication(self.check_async)
        yield self.check_authentication_errors(self.check_async)
        yield self.check_authorization(self.check_async)
        yield self.check_authorization_errors(self.check_async)

    @common.attr(locate_delay=delay_gen, render_delay=delay_gen,
                 error_delay=delay_gen, authen_delay=delay_gen)
    @defer.inlineCallbacks
    def testMixedAsync(self):
        yield self.check_good_values(self.check_any)
        yield self.check_not_found(self.check_any)
        yield self.check_moved(self.check_any)
        yield self.check_errors(self.check_any)
        yield self.check_authentication(self.check_any)
        yield self.check_authentication_errors(self.check_any)
        yield self.check_authorization(self.check_any)
        yield self.check_authorization_errors(self.check_any)

    @defer.inlineCallbacks
    def check_good_values(self, checker):
        OK = http.Status.OK
        NA = http.Status.NOT_ACCEPTABLE

        yield checker("/", OK, "ROOT")

        yield checker("/good", OK, "GOOD")
        yield checker("/good/", OK, "GOOD")

        yield checker("/good/unicode", OK, "UNICODE")
        yield checker("/good/unicode/", OK, "UNICODE")

        yield checker("/good/unicode/plain", OK, "plain")
        yield checker("/good/unicode/plain/", OK, "plain")
        yield checker("/good/unicode/utf8", OK, "Wa\xeey\xf1")
        yield checker("/good/unicode/utf8/", OK, "Wa\xeey\xf1")

        # Default encoding do not support the content
        yield checker("/good/unicode/iso5", NA, "ERROR")
        yield checker("/good/unicode/iso5/", NA, "ERROR")
        yield checker("/good/unicode/big5", NA, "ERROR")
        yield checker("/good/unicode/big5/", NA, "ERROR")

        # Accepting the right encoding solve the issue
        yield checker("/good/unicode/utf8", OK,
                      "Wa\xc3\xaey\xc3\xb1", encodings="unicode-1-1-utf-8")
        yield checker("/good/unicode/utf8", OK,
                      "Wa\xc3\xaey\xc3\xb1", encodings="unicode-1-1-utf-8")
        yield checker("/good/unicode/iso5", OK,
                      "\xb1\xde\xe0\xd8\xe1", encodings="iso-8859-5")
        yield checker("/good/unicode/iso5", OK,
                      "\xb1\xde\xe0\xd8\xe1", encodings="iso-8859-5")
        yield checker("/good/unicode/big5", OK,
                      "\xc7B\xc7B\xc7g\xc7O\xac\xec", encodings="big5")
        yield checker("/good/unicode/big5/", OK,
                      "\xc7B\xc7B\xc7g\xc7O\xac\xec", encodings="big5")

        # Writing objects is always asynchronous
        check_async = self.check_async

        # Test mime-type negociation
        yield check_async("/good/objects/a", OK, "AAAAAA", mime=TEXT_UPPER)
        yield check_async("/good/objects/b", OK, "BBBBBB", mime=TEXT_UPPER)
        yield check_async("/good/objects/c", OK, "cccccc", mime=TEXT_LOWER)
        yield check_async("/good/objects/d", NA, "ERROR")

        # Test forcing mime-type
        yield check_async("/good/objects/a", OK, "AAAAAA",
                          mime_types=TEXT_UPPER, mime=TEXT_UPPER)
        yield check_async("/good/objects/a", OK, "aaaaaa",
                          mime_types=TEXT_LOWER, mime=TEXT_LOWER)
        yield check_async("/good/objects/b", OK, "BBBBBB",
                          mime_types=TEXT_UPPER, mime=TEXT_UPPER)
        yield check_async("/good/objects/b", NA, "ERROR",
                          mime_types=TEXT_LOWER)
        yield check_async("/good/objects/c", NA, "ERROR",
                          mime_types=TEXT_UPPER)
        yield check_async("/good/objects/c", OK, "cccccc",
                          mime_types=TEXT_LOWER, mime=TEXT_LOWER)
        yield check_async("/good/objects/d", NA, "ERROR",
                          mime_types=TEXT_UPPER)
        yield check_async("/good/objects/d", NA, "ERROR",
                          mime_types=TEXT_LOWER)

        # Test negotiated encoding and language
        yield check_async("/good/objects/n", OK, "bonjour",
                          encoding="utf8", language="fr")
        yield check_async("/good/objects/o", OK, "hello",
                          encoding="utf8", language="en")
        yield check_async("/good/objects/p", OK,
                          "\xb1\xed\xb4\xef\xce\xca\xba\xf2",
                          encoding="gb18030", language="zh")
        yield check_async("/good/objects/q", OK,
                          "\xf7\xe1\xe9\xf1\xe5\xf4\xe9\xf3\xec\xfc\xf2",
                          encoding="iso-8859-7", language="el")

        # Forcing encoding
        yield check_async("/good/objects/n", NA, "ERROR",
                          encodings="iso-8859-1")
        yield check_async("/good/objects/n", NA, "ERROR",
                          encodings="latin1")
        yield check_async("/good/objects/o", NA, "ERROR",
                          encodings="iso-8859-1")
        yield check_async("/good/objects/o", NA, "ERROR",
                          encodings="latin1")
        yield check_async("/good/objects/p", OK,
                          "\xe8\xa1\xa8\xe8\xbe\xbe\xe9\x97\xae\xe5\x80\x99",
                          encodings="utf8", encoding="utf8", language="zh")
        yield check_async("/good/objects/p", NA, "ERROR",
                          encodings="iso-8859-1")
        yield check_async("/good/objects/p", NA, "ERROR",
                          encodings="latin1")
        yield check_async("/good/objects/q", OK,
                          "\xcf\x87\xce\xb1\xce\xb9\xcf\x81\xce\xb5\xcf\x84"
                          "\xce\xb9\xcf\x83\xce\xbc\xcf\x8c\xcf\x82",
                          encodings="utf8", encoding="utf8", language="el")
        yield check_async("/good/objects/q", NA, "ERROR",
                          encodings="iso-8859-1")
        yield check_async("/good/objects/q", NA, "ERROR",
                          encodings="latin1")

        # Forcing language
        yield check_async("/good/objects/n", OK, "bonjour",
                          languages="fr", language="fr")
        yield check_async("/good/objects/n", OK, "hola",
                          languages="es", language="es")
        yield check_async("/good/objects/n", OK, "hola",
                          languages="en, es", language="es")
        yield check_async("/good/objects/n", NA, "ERROR", languages="en, zh")
        yield check_async("/good/objects/o", OK, "hello",
                          languages="en", language="en")
        yield check_async("/good/objects/o", OK, "bonjour",
                          languages="fr", language="fr")
        yield check_async("/good/objects/o", OK, "bonjour",
                          languages="fr, es", language="fr")
        yield check_async("/good/objects/o", NA, "ERROR",
                          languages="es, el",
                          allowed_encodings=("unicode-1-1-utf-8", ),
                          allowed_languages=("en", "fr"))
        yield check_async("/good/objects/p", NA, "ERROR",
                          languages="en, fr, es",
                          allowed_encodings=('gb18030', 'unicode-1-1-utf-8'),
                          allowed_languages=("zh", ))
        yield check_async("/good/objects/q", NA, "ERROR",
                          languages="en, fr, es",
                          allowed_encodings=('iso-8859-7',
                                             'unicode-1-1-utf-8'),
                          allowed_languages=("el", ))

    @defer.inlineCallbacks
    def check_not_found(self, checker):
        NF = http.Status.NOT_FOUND
        IE = http.Status.INTERNAL_SERVER_ERROR

        yield checker("/ugly", NF, "ERROR")
        yield checker("/ugly/", NF, "ERROR")
        yield checker("/good/ugly", NF, "ERROR")
        yield checker("/good/ugly/", NF, "ERROR")
        yield checker("/good/unicode/ugly", NF, "ERROR")
        yield checker("/good/unicode/ugly/", NF, "ERROR")
        yield checker("/good/objects/ugly", NF, "ERROR")
        yield checker("/good/objects/ugly/", NF, "ERROR")

        yield checker("/bad/locate/not_found/", NF, "ERROR")
        yield checker("/bad/locate/not_found/dummy", NF, "ERROR")
        yield checker("/bad/locate/not_found/dummy/", NF, "ERROR")

        yield checker("/bad/locate/overridden/", IE, "OVERRIDDEN")
        yield checker("/bad/locate/overridden/dummy", IE, "OVERRIDDEN")
        yield checker("/bad/locate/overridden/dummy/", IE, "OVERRIDDEN")

    def check_moved(self, checker):
        MP = http.Status.MOVED_PERMANENTLY

        yield self.check_sync("/bad/locate/moved/", MP, "",
                              location="http://localhost/dummy")
        yield self.check_sync("/bad/locate/moved/away", MP, "",
                              location="http://localhost/dummy")
        yield self.check_sync("/bad/locate/moved/away/", MP, "",
                              location="http://localhost/dummy")

    @defer.inlineCallbacks
    def check_errors(self, checker):
        OK = http.Status.OK
        NF = http.Status.NOT_FOUND
        NA = http.Status.NOT_ALLOWED
        NC = http.Status.NO_CONTENT
        NI = http.Status.NOT_IMPLEMENTED
        IE = http.Status.INTERNAL_SERVER_ERROR
        GO = http.Status.GONE
        MP = http.Status.MOVED_PERMANENTLY

        yield checker("/bad/locate", OK, "LOCATE")
        yield checker("/bad/locate/", OK, "LOCATE")

        # locate is raising the error so the resource on itself is good
        yield checker("/bad/locate/not_found", OK, "SHOULD WORK")
        yield checker("/bad/locate/overridden", OK, "SHOULD WORK")
        yield checker("/bad/locate/moved", OK, "MOVED")

        yield checker("/bad/render", OK, "RENDER")
        yield checker("/bad/render/", OK, "RENDER")

        yield checker("/bad/render/not_found", NF, "ERROR")
        yield checker("/bad/render/not_found/", NF, "ERROR")

        yield checker("/bad/render/not_allowed/", NA, "ERROR",
                      allowed_methods=("PUT", "DELETE"))

        # Not a real error
        yield checker("/bad/render/no_content", NC, "")
        yield checker("/bad/render/no_content/", NC, "")

        yield checker("/bad/render/not_implemented", NI, "ERROR")
        yield checker("/bad/render/not_implemented/", NI, "ERROR")

        yield checker("/bad/render/overridden", IE, "OVERRIDDEN")
        yield checker("/bad/render/overridden/", IE, "OVERRIDDEN")

        # Error rendering done by resource "overridden"
        yield checker("/bad/render/overridden/sub", GO, "OVERRIDDEN")
        yield checker("/bad/render/overridden/sub/", GO, "OVERRIDDEN")

    @defer.inlineCallbacks
    def check_authentication_errors(self, checker):
        UN = http.Status.UNAUTHORIZED

        yield checker("/auth", UN, "ERROR", www_auth="Basic realm=\"test\"")
        yield checker("/auth/", UN, "ERROR", www_auth="Basic realm=\"test\"")

        bad_cred = auth.BasicHTTPCredentials("bad", "cred")

        yield checker("/auth", UN, "ERROR", credentials=bad_cred)
        yield checker("/auth/", UN, "ERROR", credentials=bad_cred)

        yield checker("/auth/protected", UN, "ERROR",
                      credentials=bad_cred)
        yield checker("/auth/protected/", UN, "ERROR",
                      credentials=bad_cred)
        yield checker("/auth/protected/authorized", UN, "ERROR",
                      credentials=bad_cred)
        yield checker("/auth/protected/authorized/", UN, "ERROR",
                      credentials=bad_cred)
        yield checker("/auth/protected/authorized/yes", UN, "ERROR",
                      credentials=bad_cred)
        yield checker("/auth/protected/authorized/yes/", UN, "ERROR",
                      credentials=bad_cred)
        yield checker("/auth/protected/authorized/no", UN, "ERROR",
                      credentials=bad_cred)
        yield checker("/auth/protected/authorized/no/", UN, "ERROR",
                      credentials=bad_cred)

    def check_authorization_errors(self, checker):
        FB = http.Status.FORBIDDEN

        good_cred = auth.BasicHTTPCredentials("user", "test")

        yield checker("/auth/protected/authorized", FB, "ERROR",
                      credentials=good_cred)
        yield checker("/auth/protected/authorized/no", FB, "ERROR",
                      credentials=good_cred)
        yield checker("/auth/protected/authorized/no/", FB, "ERROR",
                      credentials=good_cred)

    @defer.inlineCallbacks
    def check_authentication(self, checker):
        OK = http.Status.OK

        good_cred = auth.BasicHTTPCredentials("user", "test")

        yield checker("/auth", OK, "AUTH", credentials=good_cred)
        yield checker("/auth/", OK, "AUTH", credentials=good_cred)

        yield checker("/auth/protected", OK, "PROTECTED",
                      credentials=good_cred)
        yield checker("/auth/protected/", OK, "PROTECTED",
                      credentials=good_cred)

    @defer.inlineCallbacks
    def check_authorization(self, checker):
        OK = http.Status.OK

        good_cred = auth.BasicHTTPCredentials("user", "test")

        yield checker("/auth/protected/authorized/", OK, "AUTHORIZED",
                      credentials=good_cred)
        yield checker("/auth/protected/authorized/yes", OK, "YES",
                      credentials=good_cred)
        yield checker("/auth/protected/authorized/yes/", OK, "YES",
                      credentials=good_cred)

    def setUp(self):
        common.TestCase.setUp(self)

        extra = {"locate_delay": self.locate_delay,
                 "render_delay": self.render_delay,
                 "error_delay": self.error_delay}

        # Building resource tree
        root = DummyResource(render_content="ROOT",
                             error_content="ERROR", **extra)

        good = DummyResource(render_content="GOOD", **extra)
        bad = DummyResource(render_content="BAD", **extra)
        root["good"] = good
        root["bad"] = bad

        # Authentication testing

        authen = DummyAuthenticator("test", {"user": "test"},
                                    auth_delay=self.authen_delay)
        authenticated = DummyResource(render_content="AUTH",
                                      authenticator=authen, **extra)
        root["auth"] = authenticated

        protected = DummyResource(render_content="PROTECTED", **extra)
        authenticated["protected"] = protected

        auth_locs = ["/auth/protected/authorized/",
                     "/auth/protected/authorized/yes",
                     "/auth/protected/authorized/yes/"]
        authorizer = DummyAuthorizer(auth_locs, auth_delay=self.author_delay)
        authorized = DummyResource(render_content="AUTHORIZED",
                                   authorizer=authorizer, **extra)
        protected["authorized"] = authorized

        yes = DummyResource(render_content="YES", **extra)
        no = DummyResource(render_content="NO", **extra)
        authorized["yes"] = yes
        authorized["no"] = no

        # Error testing

        locate = DummyResource(render_content="LOCATE", **extra)
        render = DummyResource(render_content="RENDER", **extra)
        bad["locate"] = locate
        bad["render"] = render

        lnf = DummyResource(render_content="SHOULD WORK",
                            locate_error=http.NotFoundError(), **extra)
        locate["not_found"] = lnf

        error = http.InternalServerError()
        lov = DummyResource(render_content="SHOULD WORK",
                            locate_error=error,
                            error_content="OVERRIDDEN", **extra)
        locate["overridden"] = lov

        error = http.MovedPermanently(location="http://localhost/dummy")
        lmp = DummyResource(render_content="MOVED",
                            locate_error=error, **extra)
        locate["moved"] = lmp

        rnf = DummyResource(render_error=http.NotFoundError(), **extra)

        render["not_found"] = rnf

        error = http.NotAllowedError(allowed_methods=(http.Methods.PUT,
                                                      http.Methods.DELETE))
        rna = DummyResource(render_error=error, **extra)

        render["not_allowed"] = rna

        error = http.HTTPError(status=http.Status.NO_CONTENT)
        rnc = DummyResource(render_error=error, **extra)

        render["no_content"] = rnc

        error = http.HTTPError(status=http.Status.NOT_IMPLEMENTED)
        rni = DummyResource(render_error=error, **extra)

        render["not_implemented"] = rni

        rov = DummyResource(render_error=http.InternalServerError(),
                            error_content="OVERRIDDEN", **extra)
        render["overridden"] = rov

        sub = DummyResource(render_error=http.GoneError(), **extra)
        rov["sub"] = sub

        # Normal behaviours
        # Unicode values

        unicode = DummyResource(render_content="UNICODE", **extra)
        good["unicode"] = unicode

        iso5 = DummyResource(render_content=u"Борис", **extra)
        big5 = DummyResource(render_content=u"オオハシ科", **extra)
        utf8 = DummyResource(render_content=u"Waîyñ", **extra)
        plain = DummyResource(render_content=u"plain", **extra)

        unicode["plain"] = plain
        unicode["iso5"] = iso5
        unicode["big5"] = big5
        unicode["utf8"] = utf8

        # Object values

        objects = DummyResource(render_content="OBJECTS", **extra)
        good["objects"] = objects

        a = DummyResource(render_content=A("AaAaAa"), **extra)
        b = DummyResource(render_content=B("BbBbBb"), **extra)
        c = DummyResource(render_content=C("CcCcCc"), **extra)
        d = DummyResource(render_content=D("DdDdDd"), **extra)

        objects["a"] = a
        objects["b"] = b
        objects["c"] = c
        objects["d"] = d

        values = {"fr": "bonjour", "es": "hola", "en": "hello",
                  "zh": u"表达问候", "el": u"χαιρετισμός"}

        n1 = Negotiable(values, ("utf8", ), ("fr", "es"))
        n2 = Negotiable(values, ("utf8", ), ("en", "fr"))
        n3 = Negotiable(values, ("gb18030", "utf8"), ("zh", ))
        n4 = Negotiable(values, ("iso-8859-7", "utf8"), ("el", ))
        n = DummyResource(render_content=n1, **extra)
        o = DummyResource(render_content=n2, **extra)
        p = DummyResource(render_content=n3, **extra)
        q = DummyResource(render_content=n4, **extra)

        objects["n"] = n
        objects["o"] = o
        objects["p"] = p
        objects["q"] = q

        # Setting up writer/reader registry
        registry = document.Registry()
        registry.register_writer(_write_upper, TEXT_UPPER, IA)
        registry.register_writer(_write_lower, TEXT_LOWER, IA)
        registry.register_writer(_write_upper, TEXT_UPPER, IB)
        registry.register_writer(_write_lower, TEXT_LOWER, IC)
        registry.register_writer(_write_negotiable, TEXT_PLAIN, IN)

        # Creating server
        self.server = webserver.Server(0, root, registry=registry)
        self.server._scheme = http.Schemes.HTTP

        # Enabling mime types
        self.server.enable_mime_type(TEXT_PLAIN, 0.8)
        self.server.enable_mime_type(TEXT_UPPER, 0.5)
        self.server.enable_mime_type(TEXT_LOWER, 0.1)

    @defer.inlineCallbacks
    def testElfLog(self):
        path = tempfile.mktemp()
        self.addCleanup(os.unlink, path)

        format = ('time date cs-method cs-uri bytes time-taken c-ip s-ip '
                  'sc-status sc-comment cs-uri-stem cs-uri-query '
                  'sc(Content-Type) cs(Accept)')
        elf = webserver.ELFLog(path, format)
        elf.init()
        self.addCleanup(elf.cleanup)
        self.server.statistics = elf

        # the file should have been created from __init__()
        self.assertTrue(os.path.exists(path))
        content = open(path).read()
        self.assertIn('#Version: 1.0', content)
        self.assertIn('#Date', content)
        self.assertIn('#Fields: %s' % (format, ), content)

        yield self.check_async('/?name=2', 404, 'ERROR')

        content = open(path).read()
        last_line = content.split("\n")[-2]
        parts = last_line.split(' ')
        self.assertEquals('GET', parts[2])
        self.assertEquals('/?name=2', parts[3])
        self.assertEquals('5', parts[4])
        self.assertEquals('127.0.0.1', parts[6])
        self.assertEquals('127.0.0.2', parts[7])
        self.assertEquals('404', parts[8])
        self.assertEquals('NOT_FOUND', parts[9])
        self.assertEquals('/', parts[10])
        self.assertEquals('?name=2', parts[11])
        self.assertEquals('"text/plain"', parts[12])
        self.assertEquals('"*"', parts[13])

        # now simulate rotating
        os.unlink(path)
        elf._reopen_output_file()

        self.assertTrue(os.path.exists(path))
        content = open(path).read()
        self.assertIn('Version: 1.0', content)
        self.assertIn('Date', content)
        self.assertIn('Fields: %s' % (format, ), content)


def _write_upper(doc, obj):
    doc.write(obj.value.upper())


def _write_lower(doc, obj):
    doc.write(obj.value.lower())


def _write_negotiable(doc, obj):
    if doc.encoding not in obj.allowed_encodings:
        raise Exception("Invalid encoding negotiated")
    if doc.language not in obj.allowed_languages:
        raise Exception("Invalid language negotiated")
    doc.write(obj.values[doc.language])
