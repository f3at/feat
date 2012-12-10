from zope.interface import Interface, Attribute, implements

from twisted.internet import reactor
from twisted.internet.protocol import ClientFactory

from feat.common import defer, error, log, time
from feat.web import http, security


DEFAULT_CONNECT_TIMEOUT = 30


class RequestError(error.FeatError):
    pass


class RequestCanceled(RequestError):
    pass


class InvalidResponse(RequestError):
    pass


class RequestTimeout(RequestError):
    pass


class IHTTPClientOwner(Interface):

    response_timeout = Attribute("Maximum time waiting for a response")
    idle_timeout = Attribute("Maximum time waiting for response's body")

    def onClientConnectionFailed(reason):
        pass

    def onClientConnectionMade(protocol):
        pass

    def onClientConnectionLost(protocol, reason):
        pass


class Response(object):

    def __init__(self):
        self.status = None
        self.headers = {}
        self.length = None
        self.body = None


class Protocol(http.BaseProtocol):

    log_category = "http-client"

    owner = None

    def __init__(self, log_keeper, owner):
        if owner is not None:
            owner = IHTTPClientOwner(owner)

            if getattr(owner, "response_timeout", None) is not None:
                self.firstline_timeout = owner.response_timeout
                self.inactivity_timeout = owner.response_timeout

            if getattr(owner, "idle_timeout", None) is not None:
                self.idle_timeout = owner.idle_timeout

            self.owner = owner

        http.BaseProtocol.__init__(self, log_keeper)

        self._response = None
        self._requests = []

        self.debug("HTTP client protocol created")

    def is_idle(self):
        return http.BaseProtocol.is_idle(self) and not self._requests

    def request(self, method, location,
                protocol=None, headers=None, body=None):
        headers = dict(headers) if headers is not None else {}
        if body:
            # without typecast to str, in case of unicode input
            # the server just breaks connection with me
            # TODO: think if it cannot be fixed better
            body = body.encode('utf-8')
            headers["content-length"] = len(body)
        lines = []
        http.compose_request(method, location, protocol, buffer=lines)
        http.compose_headers(headers, buffer=lines)

        seq = []
        for line in lines:
            line = line.encode('utf-8')
            self.log("<<< %s", line)
            seq.append(line)
            seq.append("\r\n")
        seq.append("\r\n")

        if body:
            seq.append(body)

        d = defer.Deferred()
        self._requests.append(d)

        self.transport.writeSequence(seq)

        return d

    ### Overridden Methods ###

    def onConnectionMade(self):
        self.factory.onConnectionMade(self)

    def onConnectionLost(self, reason):
        self.factory.onConnectionLost(self, reason)
        self.owner = None

    def process_cleanup(self, reason):
        for d in self._requests:
            d.errback(RequestError())
        self._requests = None

    def process_reset(self):
        self._response = None

    def process_request_line(self, line):
        assert self._response is None, "Already handling response"
        parts = http.parse_response_status(line)
        if parts is None:
            error = InvalidResponse("Wrong response format: %r", line)
            self._client_error(error)
            return
        protocol, status = parts
        self._response = Response()
        self._response.protocol = protocol
        self._response.status = status

        # HTTP 1.0 doesn't require Content-Length or Transfer-Encoding
        # response headers. It can simply start printing body after the
        # headers section and close the connection when it's done.
        # This requires special decoder which might be overwritten later
        # if one of the mentioned headers is received.
        # Moreover even though HTTP 1.1 defines that either Content-Length
        # or Transfer-Encoding is required, there are servers out there
        # which claim to speak HTTP 1.1 really speak HTTP 1.0.
        # One example I've seen is combination of:
        # < Server: Microsoft-IIS/6.0
        # < X-Powered-By: PHP/5.3.8
        # but its most probably not the only one. Therefore the only way
        # to support this is to assume content decoder and overwrite it later.
        self._setup_identity_decoding(length=None)

    def process_length(self, length):
        assert self._response is not None, "No response information"
        self._response.length = length

    def process_extend_header(self, name, values):
        assert self._response is not None, "No response information"
        res = self._response
        if name not in res.headers:
            res.headers[name] = []
        res.headers[name].extend(values)

    def process_set_header(self, name, value):
        assert self._response is not None, "No response information"
        self._response.headers[name] = value

    def process_body_data(self, data):
        assert self._response is not None, "No response information"
        if self._response.body is None:
            self._response.body = ''
        self._response.body += data

    def process_body_finished(self):
        d = self._requests.pop(0)
        d.callback(self._response)

    def process_timeout(self):
        self._client_error(RequestTimeout())

    def process_parse_error(self):
        self._client_error(InvalidResponse())

    ### Private Methods ###

    def _client_error(self, exception):
        if self._requests:
            d = self._requests.pop(0)
            d.errback(exception)
        self.transport.loseConnection()


class Factory(ClientFactory):

    protocol = Protocol

    def __init__(self, log_keeper, owner, deferred):
        self.owner = IHTTPClientOwner(owner)
        self.log_keeper = log_keeper
        self._deferred = deferred

    def buildProtocol(self, addr):
        return self.create_protocol(self.log_keeper, self.owner)

    def create_protocol(self, *args, **kwargs):
        proto = self.protocol(*args, **kwargs)
        proto.factory = self
        time.call_next(self._deferred.callback, proto)
        del self._deferred
        return proto

    def clientConnectionFailed(self, connector, reason):
        time.call_next(self._deferred.errback, reason)
        del self._deferred
        if self.owner:
            self.owner.onClientConnectionFailed(reason)
        self._cleanup()

    def onConnectionMade(self, protocol):
        if self.owner:
            self.owner.onClientConnectionMade(protocol)

    def onConnectionLost(self, protocol, reason):
        if self.owner:
            self.owner.onClientConnectionLost(protocol, reason)
        self._cleanup()

    ### private ###

    def _cleanup(self):
        self.log_keeper = None
        self.owner = None


class Connection(log.LogProxy, log.Logger):

    implements(IHTTPClientOwner)

    factory = Factory

    default_http_protocol = http.Protocols.HTTP11

    connect_timeout = DEFAULT_CONNECT_TIMEOUT
    response_timeout = None # Default factory one
    idle_timeout = None # Default factory one

    bind_address = None

    def __init__(self, host, port=None, protocol=None,
                 security_policy=None, logger=None):
        logger = logger or log.get_default() or log.FluLogKeeper()
        log.LogProxy.__init__(self, logger)
        log.Logger.__init__(self, logger)

        self._host = host
        self._port = port
        self._security_policy = security.ensure_policy(security_policy)

        if self._security_policy.use_ssl:
            self._http_scheme = http.Schemes.HTTPS
        else:
            self._http_scheme = http.Schemes.HTTP

        if self._port is None:
            if self._http_scheme is http.Schemes.HTTP:
                self._port = 80
            if self._http_scheme is http.Schemes.HTTPS:
                self._port = 443

        proto = self.default_http_protocol if protocol is None else protocol
        self._http_protocol = proto

        self._protocol = None
        self._pending = 0
        self.log_name = '%s:%d (%s)' % (
            self._host, self._port, self._http_scheme.name)
        self.debug('Connection to %s:%d using %s',
            self._host, self._port, self._http_scheme.name)

    ### public ###

    def is_idle(self):
        return self._protocol is None or self._protocol.is_idle()

    def request(self, method, location, headers=None, body=None):
        self.debug('%s-ing on %s', method.name, location)
        self.log('Headers: %r', headers)
        self.log('Body: %r', body)
        if self._protocol is None:
            d = self._connect()
            d.addCallback(self._on_connected)
        else:
            d = defer.succeed(self._protocol)

        d.addCallback(self._request, method, location, headers, body)
        return d

    def disconnect(self):
        if self._protocol:
            self._protocol.transport.loseConnection()

    ### virtual ###

    def create_protocol(self, deferred):
        return self.factory(self, self, deferred)

    def onClientConnectionFailed(self, reason):
        pass

    def onClientConnectionMade(self, protocol):
        pass

    def onClientConnectionLost(self, protocol, reason):
        self._protocol = None

    ### private ###

    def _connect(self):
        d = defer.Deferred()
        factory = self.create_protocol(d)

        kwargs = {}
        if self.connect_timeout is not None:
            kwargs['timeout'] = self.connect_timeout
        kwargs['bindAddress'] = self.bind_address

        if self._security_policy.use_ssl:
            context_factory = self._security_policy.get_ssl_context_factory()
            reactor.connectSSL(self._host, self._port,
                               factory, context_factory, **kwargs)
            return d

        reactor.connectTCP(self._host, self._port, factory, **kwargs)
        return d

    def _on_connected(self, protocol):
        self._protocol = protocol
        return protocol

    def _request(self, protocol, method, location, headers, body):
        self._pending += 1
        headers = dict(headers) if headers is not None else {}
        if "host" not in headers:
            headers["host"] = self._host
        d = protocol.request(method, location,
                             self._http_protocol,
                             headers, body)
        d.addBoth(self._request_done)
        return d

    def _request_done(self, param):
        self._pending -= 1
        return param


class ConnectionPool(Connection):
    '''
    I establish and keep a number of persitent connections to a web service
    speaking HTTT 1.1 protocol.
    '''

    def __init__(self, host, port=None, protocol=None,
                 security_policy=None, logger=None,
                 maximum_connections=10):
        Connection.__init__(self, host, port, protocol,
                            security_policy, logger)
        self._connected = set()
        self._idle = set()
        # [Deferred] to be triggered when the protocol connection becomes free
        self._awaiting_client = list()
        self._max = maximum_connections

    ### public ###

    def is_idle(self):
        return all([x.is_idle() for x in self._connected])

    def disconnect(self):
        [x.cancel() for x in self._awaiting_client]
        [x.transport.loseConnection() for x in self._connected]

    def request(self, method, location, headers=None, body=None):
        self.debug('%s-ing on %s', method.name, location)
        self.log('Headers: %r', headers)
        self.log('Body: %r', body)
        try:
            protocol = self._idle.pop()
            d = defer.succeed(protocol)
        except KeyError:
            d = defer.Deferred()
            self._awaiting_client.append(d)
            if len(self._connected) < self._max:
                self._connect()
        d.addCallback(self._request, method, location, headers, body)
        return d

    def onClientConnectionFailed(self, reason):
        self.info("Failed connecting to %s:%s. Reason: %s",
                  self._host, self._port, reason)

    def onClientConnectionMade(self, protocol):
        self._connected.add(protocol)
        self._return_to_the_pool(protocol)
        self.debug("Connection made to %s:%s, pool has now %d connections "
                   "%d of with are idle", self._host, self._port,
                   len(self._connected), len(self._idle))

    def onClientConnectionLost(self, protocol, reason):
        if protocol in self._connected:
            self._connected.remove(protocol)
        if protocol in self._idle:
            self._idle.remove(protocol)
        self.debug("Connection to %s:%s lost, pool has now %d connections "
                   "%d of with are idle", self._host, self._port,
                   len(self._connected), len(self._idle))

    def _request(self, protocol, method, location, headers, body):
        d = Connection._request(
            self, protocol, method, location, headers, body)
        d.addBoth(defer.bridge_param, self._return_to_the_pool, protocol)
        return d

    def _return_to_the_pool(self, protocol):
        try:
            d = self._awaiting_client.pop(0)
            d.callback(protocol)
        except IndexError:
            self._idle.add(protocol)
