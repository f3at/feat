from twisted.internet import error as terror

from feat.common import log, defer
from feat.gateway import resources
from feat.web import webserver


class NoPortAvailableError(Exception):
    pass


class Gateway(log.LogProxy, log.Logger):

    log_category = "gateway"

    def __init__(self, root, port_range=None):
        log.Logger.__init__(self, self)
        log.LogProxy.__init__(self, log.FluLogKeeper())
        self._root = root

        self._ports = port_range
        self._server = None

    def initiate_master(self):
        port = self._ports[0]
        self.log("Initializing master gateway on port %d", port)
        self._server = webserver.Server(port, resources.Root(self._root),
                                        log_keeper=self)
        self._server.initiate()
        self.info("Master gateway started on port %d", self.port)

    def initiate_slave(self):
        min, max = self._ports
        for port in xrange(min + 1, max):
            try:

                self.log("Initializing slave gateway on port %d", port)
                server = webserver.Server(port, resources.Root(self._root),
                                          log_keeper=self)
                server.initiate()
                self._server = server
                self.info("Slave gateway started on port %d", self.port)
                return

            except terror.CannotListenError:

                self.log("Port %d not available for slave gateway", port)
                continue

        raise NoPortAvailableError("No port available for slave gateway")

    def cleanup(self):
        if self._server:
            self.debug("Cleaning up gateway on port %d", self.port)
            d = self._server.cleanup()
            self._server = None
            return d
        return defer.succeed(self)

    @property
    def port(self):
        return self._server and self._server.port
