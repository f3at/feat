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
from OpenSSL import SSL

from twisted.internet import error as terror

from feat.common import log, defer
from feat.gateway import resources
from feat.web import security, http, webserver


class NoPortAvailableError(Exception):
    pass


class Gateway(log.LogProxy, log.Logger):

    log_category = "gateway"

    def __init__(self, root, port_range=None, security_policy=None):
        log.Logger.__init__(self, self)
        log.LogProxy.__init__(self, root)
        self._root = root

        self._ports = port_range
        self._security = security.ensure_policy(security_policy)
        self._server = None

    def initiate_master(self):
        port = self._ports[0]
        self.log("Initializing master gateway on port %d", port)
        self._server = webserver.Server(port, resources.Root(self._root),
                                        security_policy=self._security,
                                        log_keeper=self)
        self._server.initiate()
        self.info("Master gateway started on port %d", self.port)

    def initiate_slave(self):
        min, max = self._ports
        for port in xrange(min + 1, max):
            try:
                self.log("Initializing slave gateway on port %d", port)
                server = webserver.Server(port, resources.Root(self._root),
                                          security_policy=self._security,
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
            self.debug("Cleaning up gateway on port %s", self.port)
            d = self._server.cleanup()
            self._server = None
            return d
        return defer.succeed(self)

    @property
    def port(self):
        return self._server and self._server.port
