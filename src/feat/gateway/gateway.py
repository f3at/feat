from zope.interface import Interface

from feat.common import log, defer
from feat.web import webserver


class IResolver(Interface):

    def resolve(self, recipient):
        pass


class Gateway(log.FluLogKeeper, log.Logger):

    log_category = "gateway"

    def __init__(self, agency, port=None):
        log.Logger.__init__(self, self)
        self._agency = agency
        self._resolver = IResolver(agency)
        self._port = port
        self._server = None

    def initialise(self):
        self.debug("Initializing gateway on port %d", self._port)
        root = RootResource(self)
        self._server = webserver.Server(self._port, root)
        self._server.initialize()
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


class RootResource(webserver.BasicResource):

    def __init__(self, gateway):
        self._gateway = gateway

    def render_resource(self, request, response, location):
        response.set_mime_type("text/html")
        return """<HTML><HEAD><TITLE>F3AT Gateway</TITLE></HEAD>
                  <BODY><P></P></BODY></HTML>"""
