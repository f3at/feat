from feat.common import log, defer
from feat.gateway import resources
from feat.web import webserver


class Gateway(log.FluLogKeeper, log.Logger):

    log_category = "gateway"

    def __init__(self, root, port=None):
        log.Logger.__init__(self, self)
        self._root = root

        self._port = port
        self._server = None

    def initiate(self):
        self.debug("Initializing gateway on port %d", self._port)
        self._server = webserver.Server(self._port, resources.Root(self._root))
        self._server.initiate()
        self.debug("Gateway initialized on port %d", self.port)

    def cleanup(self):
        if self._server:
            self.debug("Cleaning up gateway on port %d", self.port)
            d = self._server.cleanup()
            self._server = None
            return d
        return defer.succeed(self)

    @property
    def port(self):
        return self._port
