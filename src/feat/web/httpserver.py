from zope.interface import Interface, Attribute

from twisted.internet import protocol
from twisted.web.http import StringTransport

from feat.common import log, time, error
from feat.web import http
from feat.web.http import HTTPError


RAW_DATA = 0
LINE_DATA = 1


class IHTTPServerOwner(Interface):

    request_timeout = Attribute("Maximum time to receive first line "
                                "after client connects")
    idle_timeout = Attribute("Maximum time waiting for request's body")

    def onServerConnectionMade(channel):
        pass

    def onServerConnectionLost(channel, reason):
        pass


class BaseRequest(object):
    """
    Abstract class to define the public method Protocol needs.
    """

    def __init__(self, channel):
        self.channel = channel

    def initiate(self):
        """Called by the channel when the request has been setup."""

    def activate(self):
        """Called by the channel when data can be written to the transport."""

    def dataReceived(self, data):
        """Called by the channel when data is received"""

    def allContentReceived(self):
        """Called by the channel when all the content has been received"""

    def connectionLost(self, reason):
        """Called by the channel when the connection has been lost"""


class Request(BaseRequest, log.Logger):
    """
    Base class for HTTP requests.

    Requests are created by the RequestFactory AFTER the channel
    received the request line and all the headers. This way,
    the factory can create different type of request in function
    of the request/headers.
    """

    log_ident = "request"

    def __init__(self, channel, info, active):
        log.Logger.__init__(self, channel)

        peer = channel.transport.getPeer()
        self.log_name = "%s:%s" % (peer.host, peer.port)
        self.debug('Creating %s', self.log_ident)

        BaseRequest.__init__(self, channel)

        self.request_protocol = info.protocol

        self.method = info.method
        self.uri = info.uri

        self._body_length = info.length
        self._received_headers = {}
        self._received_cookies = {}
        self._received_length = None
        self.received_bytes = 0

        self.protocol = info.protocol

        self._headers = {}
        self._cookies = {}

        self._length = None # No length by default
        self.bytes_sent = 0 # Bytes of BODY written (headers do not count)

        self.initiated = False # If the request has been initiated
        self.activated = False # If the request can write to the channel
        self.writing = False   # If already started writing data
        self.finished = False  # If the request is finished
        self.persistent = True # If the connection must be kept
        self.received = False  # If all body content received

        self.status_code = http.Status.OK
        self.status_message = http.get_status_message(self.status_code)

        self._parse_headers(info.headers)

        self.transport_activated = False
        self.transport = None
        if not active:
            self.transport = StringTransport()

    ### Virtual Methods ###

    def onInitiate(self):
        pass

    def onActivate(self):
        pass

    def onDataReceived(self, data):
        pass

    def onAllContentReceived(self):
        pass

    def onConnectionLost(self, reason):
        pass

    ### Public Methods ###

    def initiate(self):
        self.debug('Initiating %s', self.log_ident)
        assert not self.initiated, "Already initiated"
        self.initiated = True

        try:
            self.onInitiate()
        except HTTPError, e:
            self.warning("Error during initiation: %s",
                         error.get_exception_message(e))
            self._make_error(e.status_code, e.status_message)
        except Exception, e:
            self.warning("Error during initiation: %s",
                         error.get_exception_message(e))
            self._make_error(http.Status.INTERNAL_SERVER_ERROR)
            raise

        if self.transport is None:
            # Started active, so activate right away
            self.activate()

    def activate(self):
        self.debug('Activating %s', self.log_ident)
        assert not self.activated, "request already active"
        self.activated = True

        self._activate_transport()

        if self.finished:
            # The request was finished before being activated
            time.call_later(0, self._cleanup)
            return

        try:
            self.onActivate()
        except HTTPError, e:
            self.warning("Error during activation: %s",
                         error.get_exception_message(e))
            self._make_error(e.status_code, e.status_message)
        except Exception, e:
            self.warning("Error during activation: %s",
                         error.get_exception_message(e))
            self._make_error(http.Status.INTERNAL_SERVER_ERROR)
            raise

    def dataReceived(self, data):
        self.received_bytes += len(data)

        if self.finished:
            return

        try:
            self.onDataReceived(data)
        except HTTPError, e:
            self.warning("Error during data processing: %s",
                         error.get_exception_message(e))
            self._make_error(e.status_code, e.status_message)
            return
        except Exception, e:
            self.warning("Error during data processing: %s",
                         error.get_exception_message(e))
            self._make_error(http.Status.INTERNAL_SERVER_ERROR)
            raise

    def allContentReceived(self):
        self.debug('All content received on %s', self.log_ident)
        assert not self.received, "Already been notified"
        if self.finished:
            return
        self.received = True
        try:
            self.onAllContentReceived()
        except HTTPError, e:
            self.warning("Error during finalization: %s",
                         error.get_exception_message(e))
            self._make_error(e.status_code, e.status_message)
            return
        except Exception, e:
            self.warning("Error during finalization: %s",
                         error.get_exception_message(e))
            self._make_error(http.Status.INTERNAL_SERVER_ERROR)
            raise

    def connectionLost(self, reason):
        self.debug('Connection lost for %s: %s', self.log_ident,
                   reason.getErrorMessage())
        try:
            self.onConnectionLost(reason)
        except HTTPError:
            pass

    def http_error(self, code, message=None):
        self.debug('Error %d on %s', code, self.log_ident)
        assert not self.writing, "Header already sent"
        self._make_error(code, message)
        raise HTTPError(name=message, status=code)

    def finish(self):
        self.debug('Finishing %s', self.log_ident)
        assert not self.finished, "Request already finished"
        self.finished = True

        # If not all the body has been read, we must disconnect
        if self._body_length and not self.received:
            self.persistent = False

        self._write_headers()

        if self.activated:
            time.call_later(0, self._cleanup)

    def write(self, data):
        if data:
            self._write_headers()
            if self._length is not None:
                total = len(data) + self.bytes_sent
                if total > self._length:
                    raise HTTPError("Ask to send %d more bytes than "
                                    "the specified content length %d"
                                    % (total - self._length, self._length))
            self.bytes_sent += len(data)
            self.transport.write(data)

    def has_received_header(self, name):
        return name.lower() in self._received_headers

    def get_received_header(self, name):
        return self._received_headers.get(name.lower())

    def get_received_length(self):
        return self._received_length

    def get_received_cookie(self, name):
        return self._received_cookies.get(name)

    def has_header(self, name):
        return name.lower() in self._headers

    def get_header(self, name):
        return self._headers.get(name.lower())

    def set_header(self, name, value):
        assert not self.writing, "Header already sent"
        header = name.lower()
        if http.is_header_multifield(header):
            if header not in self._headers:
                self._headers[header] = []
            fields = self._headers[header]
            if isinstance(value, list):
                fields.extend(value)
            else:
                fields.extend([f.strip() for f in value.split(",")])
            self._headers[header] = fields
        else:
            self._headers[header] = value

    def clear_headers(self):
        assert not self.writing, "Header already sent"
        self._headers.clear()

    def remove_header(self, name):
        assert not self.writing, "Header already sent"
        del self._headers[name.lower()]

    def set_length(self, length):
        assert not self.writing, "Header already sent"
        self._length = int(length)
        self.set_header("content-length", str(length))

    def set_response_code(self, code, message=None):
        assert not self.writing, "Header already sent"
        self.status_code = code
        if message:
            self.status_message = message
        else:
            self.status_message = http.get_status_message(self.status_code)

    def add_cookie(self, name, payload):
        assert not self.writing, "Header already sent"
        self._cookies[name] = payload

    def parse_user_agent(self):
        agent = self.get_received_header("user-agent")
        if not agent:
            return "unknown", None
        return http.parse_user_agent(agent)


    ### Private Methods ###

    def _activate_transport(self):
        if self.transport_activated:
            return
        old = self.transport
        self.transport = self.channel.transport
        if old is not None:
            self.transport.write(old.getvalue())
        self.transport_activated = True

    def _make_error(self, code, message=None):
        self.persistent = False
        if not self.finished:
            if not self.writing:
                self.set_response_code(code, message)
                self.clear_headers()
            self.finish()

    def _parse_headers(self, headers):
        for name, value in headers.items():
            key = name.lower()
            self._received_headers[key] = value

            if key == 'content-length':
                self._received_length = int(value)
                continue

            # Check if the connection should be kept alive
            if key == 'connection':
                tokens = map(str.lower, value)
                if self.request_protocol == http.Protocols.HTTP11:
                    self.persistent = 'close' not in tokens
                else:
                    self.persistent = 'keep-alive' in tokens
                continue

            # Parse cookies
            if key == 'cookie':
                for cook in value.split(';'):
                    cook = cook.lstrip()
                    try:
                        k, v = cook.split('=', 1)
                        self._received_cookies[k] = v
                    except ValueError:
                        pass
                continue

    def _write_headers(self):
        if not self.writing:
            # Last header modifications

            if self._length is None:
                # If no length specified, it can't be a persistent connection
                self.persistent = False

            if self.protocol == http.Protocols.HTTP11:
                if not self.persistent:
                    self.set_header("connection", "close")
            elif self.protocol == http.Protocols.HTTP10:
                if self.persistent:
                    self.set_header("connection", "Keep-Alive")
            else:
                self.persistent = False

            self.debug('Writing headers on %s', self.log_ident)
            self.writing = True

            lines = []

            http.compose_response(self.status_code, self.protocol,
                                  self.status_message, buffer=lines)
            http.compose_headers(self._headers, buffer=lines)
            http.compose_cookies(self._cookies, buffer=lines)

            seq = []
            for line in lines:
                self.log("<<< %s", line)
                seq.append(line)
                seq.append("\r\n")
            seq.append("\r\n")

            self._activate_transport()

            self.transport.writeSequence(seq)

    def _cleanup(self):
        self.debug('%s done; received %s out of %s bytes',
                   self.log_ident, self.received_bytes, self._received_length)
        self.channel.request_done(self)
        del self.channel


class ErrorRequest(BaseRequest):
    """
    Request that just write an error and finish.

    Can be used by the request factory in case of error.
    """

    def __init__(self, channel, info, active, code, message=None):
        BaseRequest.__init__(self, channel)

        self.protocol = info.protocol
        self.status_code = code
        self.status_message = http.get_status_message(self.status_code)
        self.persistent = False
        if active:
            self.activate()

    def activate(self):
        response = "%s %s %s\r\n\r\n" % (self.protocol.name, self.status_code,
                                         self.status_message)
        self.channel.transport.write(response)
        time.call_later(0, self._cleanup)

    def _cleanup(self):
        self.channel.request_done(self)
        del self.channel


class RequestFactory(object):

    request_class = Request

    def __init__(self, channel):
        pass

    def buildRequest(self, channel, info, active):
        return self.request_class(channel, info, active)


class RequestInfo(object):

    def __init__(self):
        self.protocol = None
        self.headers = {}
        self.method = None
        self.uri = None
        self.length = None


class Channel(http.BaseProtocol, log.LogProxy):

    log_category = "http-server"

    owner = None

    def __init__(self, log_keeper, owner, force_version=None):
        if owner is not None:
            owner = IHTTPServerOwner(owner)

            if getattr(owner, "request_timeout", None) is not None:
                self.firstline_timeout = owner.request_timeout
                self.inactivity_timeout = owner.request_timeout

            if getattr(owner, "idle_timeout", None) is not None:
                self.idle_timeout = owner.idle_timeout

            self.owner = owner

        http.BaseProtocol.__init__(self, log_keeper)
        log.LogProxy.__init__(self, log_keeper)

        self.authenticated = False
        self.force_version = force_version
        self._requests = []
        self._protocol = None
        self._reqinfo = None

        self.debug("HTTP server protocol created")

    ### public ###

    def is_idle(self):
        return http.BaseProtocol.is_idle(self) and not self._requests

    def disconnect(self):
        self.transport.loseConnection()

    def request_done(self, request):
        """Called by the active request when it is done writing"""
        if self._requests is None:
            # Channel been cleaned up because the connection was lost.
            return

        assert request == self._requests[0], "Unexpected request done"
        del self._requests[0]

        if request.persistent:
            # Activate the next request in the pipeline if any
            if self._requests:
                self._requests[0].activate()
        else:
            self.transport.loseConnection()

    def close(self):
        self.debug("Channel closed")
        for request in list(self._requests):
            request.finish()
        self.transport.loseConnection()

    ### Overridden Methods ###

    def onConnectionMade(self):
        self.factory.onConnectionMade(self)

    def onConnectionLost(self, reason):
        self.factory.onConnectionLost(self, reason)
        self.owner = None

    def process_cleanup(self, reason):
        for request in self._requests:
            request.connectionLost(reason)
        self._requests = None

    def process_reset(self):
        self._protocol = None
        self._reqinfo = None

    def process_request_line(self, line):
        assert self._reqinfo is None, "Already handling request"
        parts = line.split()
        if len(parts) != 3:
            self.http_bad_request()
            return

        method_name, uri, protocol_name = parts

        try:
            method = http.Methods[method_name]
            protocol = http.Protocols[protocol_name]
        except KeyError:
            self._http_bad_request()

        if self.force_version and protocol != self.force_version:
            self._http_version_not_supported()
            return

        assert self._reqinfo is None, "Already have a request info"
        self._protocol = protocol
        self._reqinfo = RequestInfo()
        self._reqinfo.protocol = protocol
        self._reqinfo.method = method
        self._reqinfo.uri = uri

    def process_length(self, length):
        assert self._reqinfo is not None, "No request information"
        self._reqinfo.length = length

    def process_extend_header(self, name, values):
        assert self._reqinfo is not None, "No request information"
        info = self._reqinfo
        if name not in info.headers:
            info.headers[name] = []
        info.headers[name].extend(values)

    def process_set_header(self, name, value):
        assert self._reqinfo is not None, "No request information"
        self._reqinfo.headers[name] = value

    def process_body_start(self):
        assert self._reqinfo is not None, "No request information"
        info = self._reqinfo
        activate = len(self._requests) == 0
        request = self.request_factory.buildRequest(self, info, activate)
        self._requests.append(request)
        request.initiate()

    def process_body_data(self, data):
        assert self._requests, "No receiving request"
        request = self._requests[-1]
        request.dataReceived(data)

    def process_body_finished(self):
        assert self._requests, "No receiving request"
        request = self._requests[-1]
        request.allContentReceived()

    def process_timeout(self):
        self._http_timeout()

    def process_parse_error(self):
        self._http_bad_request()

    ### Private Methods ###

    def _http_bad_request(self):
        self._http_error(400)

    def _http_internal_server_error(self):
        self._http_error(500)

    def _http_version_not_supported(self):
        self._http_error(505)

    def _http_timeout(self):
        self._http_error(408)

    def _http_error(self, status_code, message=None):

        def respond():
            msg = message or http.get_status_message(status_code)
            protocol = self._protocol or http.Protocols.HTTP10
            resp = "%s %d %s\r\n\r\n" % (protocol.name, status_code, msg)
            self.transport.write(resp)

        # If we can, respond with the error status
        if self._requests:
            if not self._requests[0].writing:
                respond()

        self.transport.loseConnection()


class Factory(protocol.ServerFactory):

    channel_class = Channel
    request_factory_class = RequestFactory

    def __init__(self, log_keeper, owner=None):
        self.log_keeper = log_keeper
        self.owner = owner
        self._channels = []

    def is_idle(self):
        return all([p.is_idle() for p in self._channels])

    def disconnect(self):
        for channel in self._channels:
            channel.disconnect()

    def buildProtocol(self, addr):
        return self.create_protocol(self.log_keeper, self.owner)

    def create_protocol(self, *args, **kwargs):
        proto = self.channel_class(*args, **kwargs)
        request_factory = self.request_factory_class(proto)
        proto.factory = self
        proto.request_factory = request_factory
        self._channels.append(proto)
        return proto

    def onConnectionMade(self, channel):
        if self.owner:
            self.owner.onServerConnectionMade(channel)

    def onConnectionLost(self, channel, reason):
        self._channels.remove(channel)
        if self.owner:
            self.owner.onServerConnectionLost(channel, reason)
