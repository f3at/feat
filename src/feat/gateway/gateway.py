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
import socket

from twisted.internet import error as terror

from feat.common import log, defer
from feat.gateway import resources
from feat.web import security, webserver, http

# Import supported formats
from feat.models import applicationjson
from feat.models import texthtml
from feat.models import applicationoctetstream


class NoPortAvailableError(Exception):
    pass


class Gateway(log.LogProxy, log.Logger):

    log_category = "gateway"

    def __init__(self, root, port_range=None, hostname=None,
                 static_path=None, security_policy=None,
                 log_keeper=None, label=None, web_statistics=None,
                 interface='', document_registry=None):
        log.Logger.__init__(self, self)
        log.LogProxy.__init__(self, log_keeper or log.get_default())

        self._root = root
        self._label = label
        if not static_path:
            from feat.configure import configure
            static_path = configure.gatewaydir
        self._static_path = static_path

        tmp_range = port_range
        if isinstance(tmp_range, int):
            tmp_range = (tmp_range, tmp_range)
        try:
            min_port, max_port = tmp_range
            if not (isinstance(min_port, int)
                    and isinstance(max_port, int)
                    and min_port <= max_port):
                raise ValueError()
            self._ports = (min_port, max_port)
        except ValueError:
            raise ValueError("Invalid gateway port/range specified: %r"
                             % (port_range, ))

        self._host = hostname or socket.gethostbyaddr(socket.gethostname())[0]
        self._security = security.ensure_policy(security_policy)
        self._server = None
        self._interface = interface
        self._document_registry = document_registry

        self._statistics = (web_statistics and
                            webserver.IWebStatistics(web_statistics))

    def initiate(self):
        return self._initiate(self._ports[0], self._ports[1])

    def initiate_master(self):
        return self._initiate(self._ports[0], self._ports[0], "master")

    def initiate_slave(self):
        return self._initiate(self._ports[0] + 1, self._ports[1], "slave")

    def cleanup(self):
        if self._server:
            self.debug("Cleaning up gateway on port %s", self.port)
            d = self._server.cleanup()
            self._server = None
            return d
        return defer.succeed(self)

    @property
    def port(self):
        return self._server and self._server.port

    @property
    def base_url(self):
        if self._server:
            return http.compose(scheme=self._server.scheme,
                                path='/', port=self.port,
                                host = self._host)

    ### private ###

    def _initiate(self, min_port, max_port, log_tag=""):
        log_tag = log_tag + " " if log_tag else ""
        for port in xrange(min_port, max_port + 1):
            try:
                self.debug("Initializing %sgateway on %s:%d iface %s",
                         log_tag, self._host, port, self._interface)
                server = webserver.Server(port, self._build_resource(port),
                                          security_policy=self._security,
                                          log_keeper=self,
                                          registry=self._document_registry,
                                          web_statistics=self._statistics,
                                          interface=self._interface)
                self._initiate_server(server)
                self._server = server
                self.info("%sgateway started on %s:%d".capitalize(),
                          log_tag, self._host, self.port)
                return

            except terror.CannotListenError:
                self.debug("Port %d not available for %sgateway", port,
                           log_tag)
                continue

        raise NoPortAvailableError(
            "No port available for %sgateway between %d and %d" % (
                log_tag, min_port, max_port))

    def _build_resource(self, port):
        return resources.Root(self._host, port,
                              self._root, self._label,
                              self._static_path)

    def _initiate_server(self, server):
        server.initiate()
        server.enable_mime_type(texthtml.MIME_TYPE)
        server.enable_mime_type(applicationjson.MIME_TYPE)
        server.enable_mime_type(applicationoctetstream.MIME_TYPE)
