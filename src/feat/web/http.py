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
import urllib
import urlparse

from OpenSSL import SSL

from zope.interface import Interface, Attribute, implements

from twisted.internet import ssl
from twisted.web import http

from feat.common import error, enum
from feat.web import compat


DEFAULT_PRIORITY = 1.0
DEFAULT_ENCODING = "iso-8859-1"
HEADER_ENCODING = "iso-8859-1"
DEFAULT_LANGUAGE = "en"
DEFAULT_MIMETYPE = "text/plain"

DEFAULT_URL_ENCODING = "utf8"
DEFAULT_URL_HTTP_PORT = 80
DEFAULT_URL_HTTPS_PORT = 443


### Enums ###


class Schemes(enum.Enum):

    HTTP, HTTPS = range(2)


class Status(enum.Enum):

    OK = http.OK
    CREATED = http.CREATED
    ACCEPTED = http.ACCEPTED
    NO_CONTENT = http.NO_CONTENT
    MOVED_PERMANENTLY = http.MOVED_PERMANENTLY
    BAD_REQUEST = http.BAD_REQUEST
    UNAUTHORIZED = http.UNAUTHORIZED
    FORBIDDEN = http.FORBIDDEN
    NOT_FOUND = http.NOT_FOUND
    NOT_ALLOWED = http.NOT_ALLOWED
    NOT_ACCEPTABLE = http.NOT_ACCEPTABLE
    REQUEST_TIMEOUT = http.REQUEST_TIMEOUT
    CONFLICT = http.CONFLICT
    GONE = http.GONE
    UNSUPPORTED_MEDIA_TYPE = http.UNSUPPORTED_MEDIA_TYPE
    INTERNAL_SERVER_ERROR = http.INTERNAL_SERVER_ERROR
    NOT_IMPLEMENTED = http.NOT_IMPLEMENTED
    SERVICE_UNAVAILABLE = http.SERVICE_UNAVAILABLE

    def is_error(self):
        return self >= 400


class Protocols(enum.Enum):

    HTTP10, HTTP11 = range(2)


class Methods(enum.Enum):

    HEAD, GET, POST, PUT, DELETE = range(5)


### Errors ###


class HTTPError(error.FeatError):
    default_error_name = "HTTP Error"
    default_status_code = Status.INTERNAL_SERVER_ERROR

    def __init__(self, *args, **kwargs):
        self.status_code = kwargs.pop('status', self.default_status_code)
        error.FeatError.__init__(self, *args, **kwargs)


class NotAllowedError(HTTPError):
    default_error_name = "Action Not Allowed"
    default_status_code = Status.NOT_ALLOWED

    def __init__(self, *args, **kwargs):
        self.allowed_methods = kwargs.pop('allowed_methods', ())
        HTTPError.__init__(self, *args, **kwargs)


class NotAcceptableError(HTTPError):
    default_error_name = "Resource Not Acceptable"
    default_status_code = Status.NOT_ACCEPTABLE

    def __init__(self, *args, **kwargs):
        self.allowed_mime_types = ("*/*")
        self.allowed_languages = ("*")
        self.allowed_encodings = ("*")

        mime_types = kwargs.pop('allowed_mime_types', None)
        if mime_types is not None:
            self.allowed_mime_types = mime_types

        languages = kwargs.pop('allowed_languages', None)
        if languages is not None:
            self.allowed_languages = languages

        encodings = kwargs.pop('allowed_encodings', None)

        if encodings is not None:
            self.allowed_encodings = tuple([compat.python2http(e)
                                            for e in encodings])

        HTTPError.__init__(self, *args, **kwargs)


class GoneError(HTTPError):
    default_error_name = "Resource Not Here Anymore"
    default_status_code = Status.GONE


class NotFoundError(HTTPError):
    default_error_name = "Resource Not Found"
    default_status_code = Status.NOT_FOUND


class NoContentError(HTTPError):
    default_error_name = "No Content"
    default_status_code = Status.NO_CONTENT


class BadRequestError(HTTPError):
    default_error_name = "Bad Request"
    default_status_code = Status.BAD_REQUEST


class NotAuthorizedError(HTTPError):
    default_error_name = "Not Authorized"
    default_status_code = Status.UNAUTHORIZED

    def __init__(self, *args, **kwargs):
        self.challenge = kwargs.pop("challenge", None)
        HTTPError.__init__(self, *args, **kwargs)


class ForbiddenError(HTTPError):
    default_error_name = "Forbidden"
    default_status_code = Status.FORBIDDEN


class InternalServerError(HTTPError):
    default_error_name = "Internal Server Error"
    default_status_code = Status.INTERNAL_SERVER_ERROR


class NotImplementedError(HTTPError):
    default_error_name = "Not Implemented"
    default_status_code = Status.NOT_IMPLEMENTED


class ServiceUnavailableError(HTTPError):
    default_error_name = "Service Unavailable"
    default_status_code = Status.SERVICE_UNAVAILABLE


class MovedPermanently(HTTPError):
    default_error_name = "Service Moved Permanently"
    default_status_code = Status.MOVED_PERMANENTLY

    def __init__(self, *args, **kwargs):
        self.location = kwargs.pop("location", None)
        HTTPError.__init__(self, *args, **kwargs)


### Interfaces ###


class ICachingPolicy(Interface):
    """Place holder."""


class IExpirationPolicy(Interface):
    """Place holder."""


class ISecurityPolicy(Interface):

    use_ssl = Attribute("")

    def get_ssl_context_factory(self):
        """Returns an SSL context factory."""


### Basic Implementations ###


class UnsecuredPolicy(object):

    implements(ISecurityPolicy)

    ### ISecurityPolicy Methods ###

    @property
    def use_ssl(self):
        return False

    def get_ssl_context_factory(self):
        return None


class DefaultSSLPolicy(object):

    implements(ISecurityPolicy)

    def __init__(self, serverKeyFilename, serverCertFilename,
                 sslMethod=SSL.SSLv23_METHOD):
        self._factory = ssl.DefaultOpenSSLContextFactory(serverKeyFilename,
                                                         serverCertFilename,
                                                         sslMethod)

    ### ISecurityPolicy Methods ###

    @property
    def use_ssl(self):
        return False

    def get_ssl_context_factory(self):
        return self._factory


### Utility Functions ###


def tuple2path(location, encoding=DEFAULT_URL_ENCODING):
    return "/".join([urllib.quote_plus(s.encode(encoding), safe="")
                     for s in location])


def path2tuple(path, encoding=DEFAULT_URL_ENCODING):
    parts = path.split('/')
    return tuple([urllib.unquote_plus(p).decode(encoding) for p in parts])


def urlencode(fields, encoding=DEFAULT_URL_ENCODING):
    encoded = dict([(n.encode(encoding), [v.encode(encoding) for v in values])
                    for n, values in fields.items()])
    return urllib.urlencode(encoded, True)


def urldecode(value, encoding=DEFAULT_URL_ENCODING):
    if isinstance(value, unicode):
        # Already decoded
        return http.parse_qs(value, 1)
    return dict([(n.decode(encoding), [v.decode(encoding) for v in values])
                 for n, values in http.parse_qs(value, 1).items()])


def parse(url, default_port=None, default_https_port=None):
    url = url.strip()
    parts = urlparse.urlsplit(url)
    scheme = parts.scheme
    if scheme == 'https':
        port = (parts.port or default_https_port
                or default_port or DEFAULT_URL_HTTPS_PORT)
    else:
        port = parts.port or default_port or DEFAULT_URL_HTTP_PORT
    host = parts.hostname
    port = int(port)
    path = parts.path
    query = parts.query
    if path == "":
        path = "/"
    return scheme, host, port, path, query


def compose(path, host=None, port=None, scheme=None):
    if host is None:
        # Relative url
        return path

    result = []
    result.append(scheme or "http")
    result.append("://")
    result.append(str(host))
    if port and port != 80:
        result.append(":")
        result.append(str(port))
    result.append(path)

    return "".join(result)


def mime2tuple(mime):
    parts = mime.split('/', 1)
    if len(parts) < 2:
        return parts[0].lower() or "*", "*"
    return parts[0].lower(), parts[1].lower()


def tuple2mime(value):
    if len(value) > 1:
        return "/".join([v.lower() for v in value])
    if len(value) == 1:
        return value[0].lower() + "/*"
    return "*/*"


def build_mime_tree(mime_types, addStars=False):
    result = {}
    for n, p in mime_types.items():
        type, sub = mime2tuple(n)
        priority = min(1.0, float(p))
        result.setdefault(type, {})[sub] = priority
    if addStars:
        if "*" not in result:
            result["*"] = {"*": 0.01}
        for sub in result.values():
            if "*" not in sub:
                sub["*"] = 0.01
    return result


def does_accept_mime_type(mime_type, mime_tree):
    type, sub = mime2tuple(mime_type)
    for subtree in (mime_tree.get(type, None), mime_tree.get("*", None)):
        if not subtree:
            continue
        if (sub in subtree) or ("*" in subtree):
            return True
    return False


def parse_content_type(value):
    type, params = _split_http_definition(value)
    charset = params.get("charset", DEFAULT_ENCODING)
    type = type or DEFAULT_MIMETYPE
    return type, compat.http2python(charset)


def parse_accepted_type(value):
    type, params = _split_http_definition(value)
    priority = float(params.get("q", DEFAULT_PRIORITY))
    return type, priority


def parse_accepted_charset(value):
    type, params = _split_http_definition(value)
    if type:
        type = compat.http2python(type)
    priority = float(params.get("q", DEFAULT_PRIORITY))
    return type, priority


def parse_accepted_language(value):
    type, params = _split_http_definition(value)
    priority = float(params.get("q", DEFAULT_PRIORITY))
    return type, priority


def parse_accepted_types(value):
    if not value:
        return {}
    return dict([parse_accepted_type(p) for p in value.split(',')])


def parse_accepted_charsets(value):
    if not value:
        return {}
    return dict([parse_accepted_charset(p) for p in value.split(',')])


def parse_accepted_languages(value):
    if not value:
        return {}
    return dict([parse_accepted_language(p) for p in value.split(',')])


def compose_accepted_types(types):
    results = []
    if isinstance(types, (list, tuple)):
        types = dict([(n, DEFAULT_PRIORITY) for n in types])
    for name, priority in types.items():
        if priority is None:
            priority = DEFAULT_PRIORITY
        priority = max(0.0, min(1.0, float(priority)))
        results.append("%s; q=%f" % (name, priority))
    return ", ".join(results)


def compose_accepted_charsets(charsets):
    results = []
    if isinstance(charsets, (list, tuple)):
        charsets = dict([(n, DEFAULT_PRIORITY) for n in charsets])
    for name, priority in charsets.items():
        if priority is None:
            priority = DEFAULT_PRIORITY
        priority = max(0.0, min(1.0, float(priority)))
        charset = compat.python2http(name)
        results.append("%s; q=%f" % (charset, priority))
    return ", ".join(results)


def compose_accepted_languages(languages):
    results = []
    if isinstance(languages, (list, tuple)):
        languages = dict([(n, DEFAULT_PRIORITY) for n in languages])
    for name, priority in languages.items():
        if priority is None:
            priority = DEFAULT_PRIORITY
        priority = max(0.0, min(1.0, float(priority)))
        results.append("%s; q=%f" % (name, priority))
    return ", ".join(results)


def compose_content_type(content_type, charset=None):
    if charset is None:
        return content_type
    charset = compat.python2http(charset)
    if charset in ('iso-8859-1', 'us-ascii'):
        return content_type
    return "%s; charset=%s" % (content_type, charset)


### Private Stuff ###


def _split_http_definition(value):
    type = None
    params = {}
    if value:
        sections = value.split(";")
        type = sections[0].strip()
        for p in sections[1:]:
            n, v = [v.strip() for v in p.split("=", 1)]
            params[n] = v
    return type, params
