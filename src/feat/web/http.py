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
import re

from zope.interface import Interface

from twisted.protocols import basic
from twisted.web import http

from feat.common import log, timeout, error, enum
from feat.web import compat


DEFAULT_PRIORITY = 1.0
DEFAULT_ENCODING = "iso-8859-1"
HEADER_ENCODING = "iso-8859-1"
DEFAULT_LANGUAGE = "en"
DEFAULT_MIMETYPE = "text/plain"

DEFAULT_URL_ENCODING = "utf8"
DEFAULT_URL_HTTP_PORT = 80
DEFAULT_URL_HTTPS_PORT = 443

FIRSTLINE_TIMEOUT = 60 # Maximum time after connection to receive data
REQUEST_TIMEOUT = 60 # Maximum time after request start to receive all headers
IDLE_TIMEOUT = 60 # Maximum time without receiving any data
INACTIVITY_TIMEOUT = 300 # Maximum time between two requests

MULTIFIELD_HEADERS = set(["accept",
                          "accept-charset",
                          "accept-encoding",
                          "accept-language",
                          "accept-ranges",
                          "allow",
                          "cache-control",
                          "connection",
                          "content-encoding",
                          "content-language",
                          "expect",
                          "pragma",
                          "proxy-authenticate",
                          "te",
                          "trailer",
                          "transfer-encoding",
                          "upgrade",
                          "via",
                          "warning",
                          "www-authenticate",
                          # extensions for wms
                          "x-accept-authentication",
                          "supported"])


### Enums ###


class Schemes(enum.Enum):

    HTTP = enum.value(0, "http")
    HTTPS = enum.value(1, "https")


class Status(enum.Enum):

    OK = 200
    CREATED = 201
    ACCEPTED = 202
    NON_AUTHORITATIVE_INFORMATION = 203
    NO_CONTENT = 204
    RESET_CONTENT = 205
    PARTIAL_CONTENT = 206
    MULTI_STATUS = 207

    MULTIPLE_CHOICE = 300
    MOVED_PERMANENTLY = 301
    FOUND = 302
    SEE_OTHER = 303
    NOT_MODIFIED = 304
    USE_PROXY = 305
    TEMPORARY_REDIRECT = 307

    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    PAYMENT_REQUIRED = 402
    FORBIDDEN = 403
    NOT_FOUND = 404
    NOT_ALLOWED = 405
    NOT_ACCEPTABLE = 406
    PROXY_AUTH_REQUIRED = 407
    REQUEST_TIMEOUT = 408
    CONFLICT = 409
    GONE = 410
    LENGTH_REQUIRED = 411
    PRECONDITION_FAILED = 412
    REQUEST_ENTITY_TOO_LARGE = 413
    REQUEST_URI_TOO_LONG = 414
    UNSUPPORTED_MEDIA_TYPE = 415
    REQUESTED_RANGE_NOT_SATISFIABLE = 416
    EXPECTATION_FAILED = 417
    UNPROCESSABLE_ENTITY = 422

    INTERNAL_SERVER_ERROR = 500
    NOT_IMPLEMENTED = 501
    BAD_GATEWAY = 502
    SERVICE_UNAVAILABLE = 503
    GATEWAY_TIMEOUT = 504
    HTTP_VERSION_NOT_SUPPORTED = 505
    INSUFFICIENT_STORAGE_SPACE = 507
    NOT_EXTENDED = 510

    def is_error(self):
        return self >= 400


class Protocols(enum.Enum):

    HTTP10 = enum.value(0, "HTTP/1.0")
    HTTP11 = enum.value(1, "HTTP/1.1")


class Methods(enum.Enum):

    HEAD, GET, POST, PUT, DELETE = range(5)


### Errors ###


class ParseError(error.FeatError):
    pass


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


### Implementations ###


class BaseProtocol(log.Logger, basic.LineReceiver, timeout.Mixin):

    max_headers = 20

    STATE_REQLINE = 0
    STATE_HEADERS = 1
    STATE_BODY = 2

    firstline_timeout = FIRSTLINE_TIMEOUT
    headers_timeout = REQUEST_TIMEOUT
    idle_timeout = IDLE_TIMEOUT
    inactivity_timeout = INACTIVITY_TIMEOUT

    def __init__(self, log_keeper):
        log.Logger.__init__(self, log_keeper)

        self.add_timeout("firstline", self.firstline_timeout,
                         self._on_firstline_timeout)
        self.add_timeout("headers", self.headers_timeout,
                         self._on_headers_timeout)
        self.add_timeout("idle", self.idle_timeout,
                         self._on_idle_timeout)
        self.add_timeout("inactivity", self.inactivity_timeout,
                         self._on_inactivity_timeout)

        self._reset()

    ### public ###

    def is_idle(self):
        return self._state == self.STATE_REQLINE

    ### virtual###

    def onConnectionMade(self):
        pass

    def onConnectionLost(self, reason):
        pass

    ### protected virtual ###

    def process_setup(self):
        pass

    def process_reset(self):
        pass

    def process_cleanup(self, reason):
        pass

    def process_request_line(self, line):
        pass

    def process_length(self, length):
        pass

    def process_extend_header(self, name, values):
        pass

    def process_set_header(self, name, value):
        pass

    def process_body_start(self):
        pass

    def process_body_data(self, data):
        pass

    def process_body_finished(self):
        pass

    def process_timeout(self):
        pass

    def process_error(self, exception):
        pass

    ### overridden ###

    def connectionMade(self):
        peer = self.transport.getPeer()
        self.log_name = "%s:%s" % (peer.host, peer.port)
        self.log('Connection made')
        self.process_setup()
        self.reset_timeout("firstline")
        self.onConnectionMade()

    def lineReceived(self, line):
        self.cancel_timeout("firstline")
        self.reset_timeout("idle")
        if self._state == self.STATE_REQLINE:
            # We are waiting for a request line
            self._got_request_line(line)
        elif self._state == self.STATE_HEADERS:
            # We are waiting for a header line
            self._got_header_line(line)
        else:
            self.log("Content: %s", line)
            self._handle_received(line)

    def rawDataReceived(self, data):
        if self._length:
            self.log("Content: %d bytes out of %d, %d bytes remaining",
                     len(data), self._length, self._remaining)
            self._remaining -= len(data)

        self.reset_timeout("idle")

        self._handle_received(data)

    def connectionLost(self, reason):
        self.log('Connection lost: %s', reason)

        self.cancel_all_timeouts()

        if self._body_decoder is not None:
            try:
                self._body_decoder.noMoreData()
            except Exception as e:
                self._error(e)
            else:
                self.process_body_finished()

        self._reset()
        self.process_cleanup(reason)


        # cancel timeouts again, because in case of no body
        # decoder we would have an inactivity timeout running now
        self.cancel_all_timeouts()
        self.onConnectionLost(reason)

    ### private ###

    def _on_firstline_timeout(self):
        self.warning("First line timeout")
        self._body_decoder = None
        self.process_timeout()

    def _on_headers_timeout(self):
        self.warning("Headers timeout")
        self.process_timeout()

    def _on_inactivity_timeout(self):
        self.warning("Inactivity timeout")
        self.process_timeout()

    def _on_idle_timeout(self):
        self.warning("Idle timeout")
        self.process_timeout()

    def _reset(self):
        self._state = self.STATE_REQLINE
        self._header = ''
        self._header_count = 0
        self._length = 0
        self._remaining = 0
        # flag saying that have been told that Content-Length is 0
        # thanks to it we don't have to wait for the connection to
        # close to process it
        self._no_content_follows = False

        self._body_decoder = None

    def _handle_received(self, data):
        self._body_decoder.dataReceived(data)

    def _got_request_line(self, line):
        self.log(">>> %s", line)
        assert self._state == self.STATE_REQLINE
        self.cancel_timeout("inactivity")
        self.reset_timeout("headers")

        self.process_request_line(line)

        # Now waiting for headers
        self._state = self.STATE_HEADERS

    def _got_header_line(self, line):
        assert self._state == self.STATE_HEADERS

        if line == '':
            if self._header:
                self._got_header_entry(self._header)
            self._header = ''
            self._got_all_headers()
        elif line[0] in ' \t':
            # Multi-lines header
            self._header = self._header + '\n' + line
        else:
            if self._header:
                self._got_header_entry(self._header)
            self._header = line

    def _got_header_entry(self, line):
        self.log(">>> %s", line)

        self._header_count += 1
        if self._header_count > self.max_headers:
            self._error(ParseError("Too much http headers"))
            return

        header, data = line.split(':', 1)
        header = header.lower()
        data = data.strip()

        if header == 'content-length':
            length = int(data)
            self.process_length(length)
            self._length = length
            self._remaining = length
            self._setup_identity_decoding(length)
        elif header == 'transfer-encoding':
            if data.lower() != "chunked":
                error = ParseError("Unsupported transfer encoding: %s" % data)
                self._error(error)
                return
            self._setup_chunked_decoding()

        if is_header_multifield(header):
            values = [f.strip() for f in data.split(",")]
            self.process_extend_header(header, values)
        elif header == 'set-cookie':
            self.process_extend_header(header, (data, ))
        else:
            self.process_set_header(header, data)

    def _got_all_headers(self):
        self.log("All headers received")
        assert self._state == self.STATE_HEADERS

        self.cancel_timeout("headers")
        self._state = self.STATE_BODY

        self.process_body_start()

        if self._body_decoder is None:
            self.debug("No content decoder, returning empty body.")
            self._got_all_content()
            return

        if self._no_content_follows:
            self._got_all_content()
            return

        self.setRawMode()

    def _got_all_content(self, extra=''):
        self.log("All content received")
        self.cancel_timeout("idle")
        self.reset_timeout("inactivity")

        self.process_body_finished()

        self._reset()
        self.process_reset()

        self.setLineMode(extra)

    def _setup_identity_decoding(self, length):
        if length == 0:
            self._no_content_follows = True
            return

        decoder = http._IdentityTransferDecoder(length,
                                                self._got_decoder_data,
                                                self._all_data_decoded)

        self._body_decoder = decoder

    def _setup_chunked_decoding(self):
        decoder = http._ChunkedTransferDecoder(self._got_decoder_data,
                                               self._all_data_decoded)
        self._body_decoder = decoder

    def _got_decoder_data(self, data):
        self.process_body_data(data)

    def _all_data_decoded(self, extra):
        self._got_all_content(extra)

    def _error(self, exception):
        self._body_decoder = None
        self.process_error(exception)


### Utility Functions ###


compose_datetime = http.datetimeToString


parse_qs = http.parse_qs


def compose_qs(args):
    if not args:
        return ""
    return urllib.urlencode([(n, v) for n, l in args.iteritems() for v in l])


def is_header_multifield(name):
    return name in MULTIFIELD_HEADERS


def get_status_message(status_code, default="Unknown"):
    return http.RESPONSES.get(status_code, default)


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
    return Schemes[scheme], host, port, path, query


def join_locations(*locations):
    if not locations:
        return None

    last = locations[0]
    result = [last]
    for loc in locations[1:]:
        if not loc:
            continue
        if last and last[-1] == "/":
            if loc[0] == "/":
                new = loc[1:]
            else:
                new = loc
        else:
            if loc and loc[0] == "/":
                new = loc
            else:
                new = "/" + loc
        if new:
            result.append(new)
            last = new

    return "".join(result)


def append_location(url, location):
    scheme, host, port, path, query = parse(url)
    return compose(join_locations(path, location), query, host, port, scheme)


def compose(path=None, query=None, host=None, port=None, scheme=None):
    if host is None:
        # Relative url
        path = path if path is not None else ""
        if query:
            return "%s?%s" % (path, query)
        return path

    result = []
    result.append(scheme.name if scheme is not None else "http")
    result.append("://")
    result.append(str(host))
    if port and port != 80:
        result.append(":")
        result.append(str(port))
    path = path if path is not None else "/"
    result.append(path)
    if query:
        result.append("?")
        result.append(query)

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


def parse_response_status(line):
    parts = line.split(' ', 2)
    if len(parts) != 3:
        return None

    try:
        status_code = int(parts[1])
    except ValueError:
        return None

    try:
        status = Status[status_code]
        protocol = Protocols[parts[0]]
    except KeyError:
        return None

    return protocol, status


def parse_user_agent(agent_header):
    agents = agent_header.split(" ", 1)
    parts = agents[0].split(",", 1)
    name, version = parts[0].split("/", 1)
    digits = version.split(".")

    def try2convert(s):
        try:
            return int(s)
        except ValueError:
            return s

    return name, tuple([try2convert(s) for s in digits])


def parse_host(host_header, scheme=Schemes.HTTP):
    parts = host_header.rsplit(":", 1)
    if len(parts) > 1:
        try:
            return parts[0], int(parts[1])
        except ValueError:
            return None
    if scheme is Schemes.HTTP:
        return parts[0], DEFAULT_URL_HTTP_PORT
    if scheme is Schemes.HTTPS:
        return parts[0], DEFAULT_URL_HTTP_PORT
    return parts[0]


def parse_header_values(header):
    parts = header.split(",")
    return dict([parse_header_value(p) for p in parts])


def parse_header_value(value):
    parts = value.split("=", 1)
    if len(parts) > 1:
        return parts[0].lower(), parts[1]
    return parts[0].lower(), None


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


def compose_user_agent(name, version=None):
    if version is None:
        return name
    if isinstance(version, int):
        return "%s/%d" % (name, version)
    return "%s/%s" % (name, ".".join([str(i) for i in version]))


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


def compose_response(status, protocol=None, message=None, buffer=None):
    buffer = buffer if buffer is not None else []
    protocol = protocol if protocol is not None else Protocols.HTTP11
    message = message if message is not None else get_status_message(status)
    buffer.append("%s %d %s" % (protocol.name, status, message))
    return buffer


def compose_request(method, uri, protocol=None, buffer=None):
    buffer = buffer if buffer is not None else []
    protocol = protocol if protocol is not None else Protocols.HTTP11
    buffer.append("%s %s %s" % (method.name, uri, protocol.name))
    return buffer


def compose_headers(headers, buffer=None):
    buffer = buffer if buffer is not None else []
    for name, value in headers.iteritems():
        # HTTP 1.1 specifies some certain header name capitalization
        # Unfortunately there are services out there (eg. SOAP) which doesn't
        # comply to the standard and require custom names like SOAPAction.
        # Consequently this method will preserve the original capitalization
        # if at least one character is passed in capital
        if not re.search(r"[A-Z]", name):
            capname = '-'.join([p.capitalize() for p in name.split('-')])
        else:
            capname = name
        if is_header_multifield(name):
            if isinstance(value, str):
                value = [value]
            buffer.append("%s: %s" % (capname, ", ".join(value)))
        else:
            buffer.append("%s: %s" % (capname, value))
    return buffer


def compose_cookies(cookies, buffer=None):
    buffer = buffer if buffer is not None else []
    for name, payload in cookies.iteritems():
        cookie = "%s=%s" % (name, payload)
        buffer.append("%s: %s" % ("Set-Cookie", cookie))
    return buffer


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
