from zope.interface import Interface, Attribute, implements

from twisted.internet import reactor as treactor, error as terror
from twisted.internet.protocol import ClientFactory, Protocol
from twisted.internet.interfaces import ISSLTransport
from twisted.python import failure

from feat.common import defer, error, log, time, first
from feat.web import http, security


DEFAULT_CONNECT_TIMEOUT = 30


class RequestError(error.FeatError):
    pass


class RequestCancelled(RequestError, defer.CancelledError):
    pass


class ConnectionReset(RequestError):
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
        self.protocol = None


class Delegate(object):

    def __init__(self, attr, name):
        self.attr = attr
        self.name = name

    def __get__(self, instance, owner):
        return getattr(instance.__dict__[self.attr], self.name)

    def __set__(self, instance, value):
        setattr(instance.__dict__[self.attr], self.name, value)


class ResponseDecoder(object, Protocol):

    protocol = Delegate('_response', 'protocol')
    status = Delegate('_response', 'status')
    headers = Delegate('_response', 'headers')
    length = Delegate('_response', 'length')
    body = Delegate('_response', 'body')

    def __init__(self):
        self._deferred = defer.Deferred()
        self._response = Response()
        self._buffer = list()

    ### IProtocol ###

    def connectionMade(self):
        pass

    def dataReceived(self, data):
        self._buffer.append(data)

    def connectionLost(self, reason=None):
        if reason:
            self._deferred.errback(reason)
        else:
            self._response.body = "".join(self._buffer)
            del self._buffer[:]
            self._deferred.callback(self._response)

    ### private interface of the decoder ###

    def get_result(self):
        return self._deferred


STATE_DESCRIPTIONS = {
    http.BaseProtocol.STATE_REQLINE: 'waiting for the status line',
    http.BaseProtocol.STATE_HEADERS: 'receiving the headers',
    http.BaseProtocol.STATE_BODY: 'receiving the response body',
    }


class Protocol(http.BaseProtocol):

    owner = None

    def __init__(self, log_keeper, owner):
        if owner is not None:
            owner = IHTTPClientOwner(owner)

            if getattr(owner, "response_timeout", None) is not None:
                self.firstline_timeout = owner.response_timeout
                self.inactivity_timeout = owner.response_timeout
                self.headers_timeout = owner.response_timeout

            if getattr(owner, "idle_timeout", None) is not None:
                self.idle_timeout = owner.idle_timeout

            self.owner = owner

        http.BaseProtocol.__init__(self, log_keeper)

        self._response = None
        self._requests = []
        # queue of Protocol instances which will receive the body
        self._pending_decoders = []

        self.log("HTTP client protocol created")

    def is_idle(self):
        return http.BaseProtocol.is_idle(self) and not self._requests

    def request(self, method, location,
                protocol=None, headers=None, body=None, decoder=None):
        self.cancel_timeout("inactivity")
        self.reset_timeout('headers')

        headers = dict(headers) if headers is not None else {}
        if body:
            body = self._encode_body(body)
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

        if decoder is None:
            decoder = ResponseDecoder()
        # The parameters below are used to format a nice error message
        # shall this request fail in any way
        scheme, host, port = self._get_target()

        decoder.request_params = {
            'method': method.name,
            'location': location,
            'scheme': scheme,
            'host': host,
            'port': port,
            'started_epoch': time.time()}

        self._requests.append(decoder)

        self.transport.writeSequence(seq)
        finished_decoding = decoder.get_result()

        d = defer.Deferred(canceller=self._cancel_request)
        # Reference to decoder is unsed by canceller
        d.decoder = decoder
        finished_decoding.chainDeferred(d)
        return d

    ### Overridden Methods ###

    def onConnectionMade(self):
        scheme, host, port = self._get_target()
        self.debug('Connected to %s://%s:%s', scheme, host, port)
        self.factory.onConnectionMade(self)

    def onConnectionLost(self, reason):
        self.factory.onConnectionLost(self, reason)
        self.owner = None

    def process_cleanup(self, reason):
        for request in self._requests:
            msg = "Connection was closed before the response was received."
            request.connectionLost(ConnectionReset(msg, cause=reason))
        self._requests = None

    def process_reset(self):
        if not self._requests:
            self.reset_timeout('inactivity')
            self.factory.onConnectionReset(self)
            self.log('Ready for new request')
        else:
            # we are still waiting for the response of the pipelined request
            pass

    def process_request_line(self, line):
        assert self._response is None, "Already handling response"
        parts = http.parse_response_status(line)
        if parts is None:
            error = InvalidResponse("Wrong response format: %r", line)
            self._client_error(error)
            return
        protocol, status = parts
        self._response = self._requests.pop(0)
        self._response.protocol = protocol
        self._response.status = status
        self._response.makeConnection(self.transport)

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
        self._response.dataReceived(data)

    def process_body_finished(self):
        self._response.connectionLost()
        self._response = None

    def process_timeout(self):
        if self._state == self.STATE_REQLINE:
            # This can be either inactivity timeout or first line timeout.
            # We don't yet have self._response set here, because we haven't
            # even received the status line.
            try:
                self._response = self._requests.pop(0)
            except IndexError:
                # this is inactivity timeout, just disconnect
                self.transport.loseConnection()
                return

        ctime = time.time()
        p = self._response.request_params
        p['elapsed'] = ctime - p['started_epoch']
        p['state_description'] = STATE_DESCRIPTIONS[self._state]
        msg = ('%(method)s to %(scheme)s'
               '://%(host)s:%(port)s%(location)s '
               'failed because of timeout '
               '%(elapsed).3fs after it was sent. '
               'When it happened it was %(state_description)s.'
               % p)
        self._client_error(RequestTimeout(msg))

    def process_parse_error(self):
        self._client_error(InvalidResponse())

    def process_error(self, exception):
        if self._response:
            self._response.connectionLost(failure.Failure(exception))
            self._response = None

    ### Private Methods ###

    def _get_target(self):
        scheme = ('https' if ISSLTransport.providedBy(self.transport) else
                  'http')
        h = self.transport.getHost()
        host = h.host
        port = h.port
        return scheme, host, port

    def _cancel_request(self, d):
        p = d.decoder.request_params
        p['elapsed'] = time.time() - p['started_epoch']
        ex = RequestCancelled('%(method)s to %(scheme)s'
                              '://%(host)s:%(port)s%(location)s '
                              'was cancelled %(elapsed).3fs'
                              ' after it was sent.' % p)
        d._suppressAlreadyCalled = True
        d.errback(ex)
        self._client_error(ex)

    def _encode_body(self, body):
        if body is None:
            return None
        if isinstance(body, unicode):
            body = body.encode('utf8', 'replace')
        if not isinstance(body, str):
            raise TypeError(repr(type(body)))
        return body

    def _client_error(self, exception):
        reason = failure.Failure(exception)
        if self._response:
            self._response.connectionLost(reason)
            self._response = None
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
        return proto

    def clientConnectionFailed(self, connector, reason):
        if reason.check(terror.TimeoutError):
            msg = ('Timeout of %s seconds expired while trying to connected to'
                   ' %s:%s' % (connector.timeout, connector.host,
                               connector.port))
            reason = failure.Failure(terror.TimeoutError(string=msg))
            reason.cleanFailure()
        elif reason.check(terror.ConnectError):
            # all the other connection errors which are not directly related
            # to the timeout
            msg = ('Failed to connect to %s:%s' %
                   (connector.host, connector.port))
            reason = failure.Failure(type(reason.value)(string=msg))
            reason.cleanFailure()

        time.call_next(self._deferred.errback, reason)
        del self._deferred
        if self.owner:
            self.owner.onClientConnectionFailed(reason)
        self._cleanup()

    def onConnectionMade(self, protocol):
        time.call_next(self._deferred.callback, protocol)
        del self._deferred
        if self.owner:
            self.owner.onClientConnectionMade(protocol)

    def onConnectionLost(self, protocol, reason):
        if self.owner:
            self.owner.onClientConnectionLost(protocol, reason)
        self._cleanup()

    def onConnectionReset(self, protocol):
        if self.owner:
            self.owner.onClientConnectionReset(protocol)

    ### private ###

    def _cleanup(self):
        self.log_keeper = None
        self.owner = None


class Connection(log.LogProxy, log.Logger):

    log_category = "http-client"

    implements(IHTTPClientOwner)

    factory = Factory

    default_http_protocol = http.Protocols.HTTP11

    connect_timeout = DEFAULT_CONNECT_TIMEOUT
    response_timeout = None # Default factory one
    idle_timeout = None # Default factory one

    bind_address = None

    def __init__(self, host, port=None, protocol=None,
                 security_policy=None, logger=None, reactor=None):
        logger = logger or log.get_default() or log.FluLogKeeper()
        log.LogProxy.__init__(self, logger)
        log.Logger.__init__(self, logger)
        self.reactor = reactor or treactor

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

    ### public ###

    def is_idle(self):
        return self._protocol is None or self._protocol.is_idle()

    def request(self, method, location, headers=None, body=None, decoder=None):
        started = time.time()
        if self._protocol is None:
            self.debug('%s-ing on %s. Creating new protocol for the request.',
                       method.name, location)
            d = self._connect()
            d.addCallback(self._on_connected)
        else:
            self.debug('%s-ing on %s. Reusing connected protocol for '
                       'the request.', method.name, location)
            d = defer.succeed(self._protocol)

        self.log('Headers: %r', headers)
        self.log('Body: %r', body)

        d.addCallback(self._request, method, location, headers, body, decoder)
        d.addBoth(defer.keep_param, self._log_request_result, method, location,
                  started)
        return d

    def disconnect(self):
        if self._protocol:
            self.debug('Disconnecting protocol')
            self._protocol.transport.loseConnection()

    ### virtual ###

    def create_protocol(self, deferred):
        return self.factory(self, self, deferred)

    def onClientConnectionFailed(self, reason):
        self.info("Failed to connect to %s:%s. Reason: %s",
                  self._host, self._port, reason)

    def onClientConnectionMade(self, protocol):
        pass

    def onClientConnectionReset(self, protocol):
        pass

    def onClientConnectionLost(self, protocol, reason):
        self.debug('Client connection lost because of %r, resetting protocol',
            reason)
        self._protocol = None

    ### private ###

    def _log_request_result(self, result, method, location, started):
        elapsed = time.time() - started
        if isinstance(result, failure.Failure):
            self.debug("%s on %s failed with error: %s. Elapsed: %.2f",
                       method.name, location, result.value, elapsed)
        else:
            self.debug('%s on %s finished with %s status, elapsed: %.2f',
                       method.name, location, int(result.status),
                       elapsed)

    def _connect(self):
        d = defer.Deferred(canceller=cancel_connector)
        factory = self.create_protocol(d)

        kwargs = {}
        if self.connect_timeout is not None:
            kwargs['timeout'] = self.connect_timeout
        kwargs['bindAddress'] = self.bind_address

        self.debug('Connecting to %s://%s:%d',
            self._http_scheme.name, self._host, self._port)

        if self._security_policy.use_ssl:
            context_factory = self._security_policy.get_ssl_context_factory()
            # the reference to connector is given to the Deferred to be
            # used by its cancellator (cancel_connector)
            d.connector = self.reactor.connectSSL(self._host, self._port,
                                             factory, context_factory,
                                             **kwargs)
        else:
            d.connector = self.reactor.connectTCP(self._host, self._port,
                                                  factory, **kwargs)

        return d

    def _on_connected(self, protocol):
        self._protocol = protocol
        return protocol

    def _request(self, protocol, method, location, headers, body, decoder):
        self._pending += 1
        headers = dict(headers) if headers is not None else {}
        if "host" not in headers:
            headers["host"] = self._host
        d = protocol.request(method, location,
                             self._http_protocol,
                             headers, body, decoder)
        d.addBoth(self._request_done)
        return d

    def _request_done(self, param):
        self._pending -= 1
        return param


def cancel_connector(d):
    if not hasattr(d, 'connector'):
        log.warning('httpclient', "The Deferred called with cancel_connector()"
                    " doesn't have the reference to the connector set.")
        return
    if d.connector.state == 'connecting':
        timeoutCall = d.connector.timeoutID
        msg = ('Connection to %s:%s was cancelled %.3f '
               'seconds after it was initialized' %
               (d.connector.host, d.connector.port,
                time.time() - timeoutCall.getTime() + d.connector.timeout))
        d.connector.stopConnecting()
        d._suppressAlreadyCalled = True

        d.errback(defer.CancelledError(msg))


class PoolProtocol(Protocol):

    def __init__(self, *args, **kwargs):
        super(PoolProtocol, self).__init__(*args, **kwargs)
        self.in_pool = False
        self.can_pipeline = None


class PoolFactory(Factory):

    protocol = PoolProtocol


class ConnectionPool(Connection):
    '''
    I establish and keep a number of persitent connections to a web service
    speaking HTTT 1.1 protocol.
    '''

    factory = PoolFactory

    def __init__(self, host, port=None, protocol=None,
                 security_policy=None, logger=None,
                 maximum_connections=10, enable_pipelineing=True,
                 response_timeout=None):

        Connection.__init__(self, host, port, protocol,
                            security_policy, logger)
        self._connected = set()
        self._idle = set()
        # [Deferred] to be triggered when the protocol connection becomes free
        self._awaiting_client = list()
        self._max = maximum_connections
        self._connecting = 0
        self._enable_pipelineing = enable_pipelineing

        # this is used by http.BaseProtocol, passing None defaults to 60s
        self.response_timeout = response_timeout

        # flag telling the error handler that this connection pool is
        # expecting all the requests to be cancelled
        self._disconnecting = False

    ### public ###

    def is_idle(self):
        return all([x.is_idle() for x in self._connected])

    def disconnect(self):
        self._disconnecting = True
        [x.cancel() for x in self._awaiting_client]
        [x.transport.loseConnection() for x in self._connected]

    def enable_pipelineing(self, value):
        self._enable_pipelineing = value

    def request(self, method, location, headers=None, body=None, decoder=None,
                outside_of_the_pool=False, dont_pipeline=False,
                reset_retry=1):
        started = time.time()
        self.debug('%s-ing on %s', method.name, location)
        self.log('Headers: %r', headers)
        self.log('Body: %r', body)
        if headers is None:
            headers = dict()
        if (not self._enable_pipelineing or
            headers.get('connection') == 'close'):
            dont_pipeline = True
        # post requests are not idempotent and should not be pipelined
        can_pipeline = (not dont_pipeline and method != http.Methods.POST and
                        reset_retry == 1)
        if self._idle and reset_retry == 1:
            self.log("Reusing existing idle connection.")
            protocol = self._idle.pop()
            d = defer.succeed(protocol)
        else:
            protocol = None
            if can_pipeline:
                protocol = first(x for x in self._connected
                                 if x.can_pipeline and x.in_pool)
            if protocol:
                self.log("The request will be pipelined.")
                d = defer.succeed(protocol)
            else:
                self.log("The request will be handled when a connection"
                         " returns to a pool.")
                d = defer.Deferred()
                self._awaiting_client.append(d)

            # Regardless if we have pipeline this request or not, check if
            # we can have more connections, so that the next request can be
            # handeled by it.
            if self._pool_len() < self._max:
                self.log("Initializing new connection.")
                self._connecting += 1
                self._connect()
        d.addCallback(self._request, method, location, headers, body, decoder,
                      outside_of_the_pool, can_pipeline)
        d.addErrback(self._handle_connection_reset, method, location,
                     headers, body, decoder, outside_of_the_pool,
                     dont_pipeline, reset_retry)
        d.addBoth(defer.keep_param, self._log_request_result,
                  method, location, started)
        return d

    def _handle_connection_reset(self, fail, method, location,
                     headers, body, decoder, outside_of_the_pool,
                     dont_pipeline, reset_retry):
        fail.trap(ConnectionReset)
        # don't retry more than 3 times or if we are disconnecting
        if reset_retry > 3 or self._disconnecting:
            return fail
        self.warning("The request will be retrying, because the underlying"
                     " connection was closed before the response was received."
                     " This is retry no %s.", reset_retry)
        return self.request(method, location,
                            headers, body, decoder, outside_of_the_pool,
                            dont_pipeline, reset_retry + 1)

    def onClientConnectionFailed(self, reason):
        if self._disconnecting:
            return
        self._connecting -= 1
        self.info("Failed connecting to %s:%s. Reason: %s",
                  self._host, self._port, reason)
        for d in self._awaiting_client:
            d.errback(reason)
        del self._awaiting_client[:]

    def onClientConnectionMade(self, protocol):
        self._connecting -= 1
        self._connected.add(protocol)
        self._return_to_the_pool(protocol)
        self.debug("Connection made to %s:%s, pool has now %d connections "
                   "%d of which are idle", self._host, self._port,
                   len(self._connected), len(self._idle))

    def onClientConnectionLost(self, protocol, reason):
        if protocol in self._connected:
            self._connected.remove(protocol)
        if protocol in self._idle:
            self._idle.remove(protocol)
        pool_len = self._pool_len()
        self.debug("Connection to %s:%s lost, pool has now %d connections "
                   "%d of with are idle. %d connections are not in the pool",
                   self._host, self._port, len(self._connected),
                   len(self._idle),
                   len(self._connected) - pool_len + self._connecting)

        possible_to_run = self._max - self._pool_len()
        if (self._awaiting_client and possible_to_run > 0):
            to_spawn = min([len(self._awaiting_client), possible_to_run])
            self.debug("Establishing %d extra connections to handle pending"
                       " connections", to_spawn)
            for x in range(to_spawn):
                self._connecting += 1
                self._connect()

    def onClientConnectionReset(self, protocol):
        self._return_to_the_pool(protocol)

    def _pool_len(self):
        return (len([x for x in self._connected if x.in_pool]) +
                self._connecting)

    def _connect(self):
        d = Connection._connect(self)
        # supress errors returned by _connect() method. They are handled by
        # clientConnectionFailed() callback
        d.addErrback(defer.override_result, None)
        return d

    def _request(self, protocol, method, location, headers, body, decoder,
                 outside_of_the_pool, can_pipeline):
        protocol.in_pool = not outside_of_the_pool
        protocol.can_pipeline = can_pipeline
        return Connection._request(self, protocol, method, location, headers,
                                   body, decoder)

    def _return_to_the_pool(self, protocol):
        try:
            d = self._awaiting_client.pop(0)
            d.callback(protocol)
        except IndexError:
            self._idle.add(protocol)
