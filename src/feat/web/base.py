import socket

from twisted.internet import reactor, error as tw_error

from feat.common import log, defer
from feat.web import http, security


class RangeServer(log.LogProxy, log.Logger):

    log_category = "base-server"

    def __init__(self, port_or_range, hostname=None,
                 security_policy=None, log_keeper=None):
        log_keeper = log_keeper or log.get_default() or log.FluLogKeeper()
        log.LogProxy.__init__(self, log_keeper)
        log.Logger.__init__(self, log_keeper)

        if hostname is None:
            hostname = socket.gethostbyaddr(socket.gethostname())[0]

        if isinstance(port_or_range, int):
            port_range = [port_or_range]
        else:
            port_range = port_or_range

        self._hostname = hostname
        self._port_range = port_range
        self._scheme = None

        self._security = security.ensure_policy(security_policy)

        self._factory = None
        self._port = None

    @property
    def port(self):
        return None if self._port is None else self._port.getHost().port

    @property
    def hostname(self):
        return self._hostname

    @property
    def scheme(self):
        return self._scheme

    @property
    def factory(self):
        return self._factory

    @property
    def is_secured(self):
        return self._scheme is http.Schemes.HTTPS

    def start_listening(self):
        assert self._port is None, "Already listening"

        if self._factory is None:
            self._factory = self._create_factory()

        if self._security.use_ssl:
            ssl_ctx_factory = self._security.get_ssl_context_factory()
            setup = self._create_ssl_setup(self._factory, ssl_ctx_factory)
        else:
            setup = self._create_tcp_setup(self._factory)

        for port in self._port_range:
            try:
                setup(port)
                break
            except tw_error.CannotListenError:
                continue

        if self._port is None:
            msg = ("Couldn't listen on any of the %d port(s) "
                   "from range starting with %d"
                   % (len(self._port_range), self._port_range[0]))
            return defer.fail(tw_error.CannotListenError(msg))

        self._on_listening()

        return defer.succeed(self)

    def stop_listening(self):

        def stopped(_):
            self._port = None
            return self

        if self._port is not None:
            d = defer.maybeDeferred(self._port.stopListening)
            d.addCallback(defer.drop_param, self._on_stopped)
            d.addCallback(stopped)
            return d

        return defer.succeed(self)

    def disconnect(self):
        if self._factory is not None:
            self._factory.disconnect()

    def cleanup(self):

        def stopped_and_clean(param):
            self._factory = None
            self._listener = None
            return param

        d = defer.succeed(None)
        d.addBoth(defer.bridge_param, self.disconnect)
        if self._listener:
            d.addBoth(defer.bridge_param, self._listener.stopListening)
        d.addBoth(stopped_and_clean)
        return d

    ### protected ##

    def _create_factory(self):
        """To be overridden"""

    def _on_listening(self):
        """To be overridden"""

    def _on_stopped(self):
        """To be overridden"""

    ### private ###

    def _create_tcp_setup(self, factory):

        def setup(port):
            self.info('TCP listening on port %r', port)
            self._port = reactor.listenTCP(port, factory) #@UndefinedVariable
            self._scheme = http.Schemes.HTTP

        return setup

    def _create_ssl_setup(self, server, ssl_ctx_factory):

        def setup(port):
            self.info('SSL listening on port %r', port)
            self._port = reactor.listenSSL(port, server, #@UndefinedVariable
                                           ssl_ctx_factory)
            self._scheme = http.Schemes.HTTPS

        return setup
