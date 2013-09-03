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
import os

from zope.interface import implements, classProvides

from feat.process import base
from feat.agents.base import alert
from feat.common import log, serialization, defer

from feat.agents.alert.interface import \
     INagiosSenderLabourFactory, IAlertSenderLabour
from feat.agents.application import feat


CODES = {alert.Severity.warn: 1,
         alert.Severity.critical: 2}


@feat.register_restorator
class Labour(log.Logger, log.LogProxy, serialization.Serializable):

    classProvides(INagiosSenderLabourFactory)
    implements(IAlertSenderLabour)

    def __init__(self, patron, config):
        log.LogProxy.__init__(self, patron)
        log.Logger.__init__(self, patron)
        self._config = config

    def send(self, alerts):
        if not self._config.monitors:
            return
        defers = [SendNSCA(self, self._config, monitor, alerts).restart()
                  for monitor in self._config.monitors]
        return defer.DeferredList(defers, consumeErrors=True)


class SendNSCA(base.Base):

    def initiate(self, config, monitor, alerts):
        self.debug('initiate send_nsca')
        self.command = config.send_nsca
        self.args = ['-H', monitor, '-c', config.config_file, '-d', ';']
        self.env = os.environ

        self._sent = False
        lines = []
        for alert in alerts:
            if alert.received_count == 0:
                code = 0
            else:
                code = CODES[alert.severity]
            status = alert.status_info or 'None specified'
            msg = ("%s;%s;%s;%s\n" % (alert.hostname, alert.description,
                                      code, status))
            lines.append(msg)
        self._body = "".join(lines)
        self._body = self._body.encode('utf-8')
        self.debug('generated body for %d alerts', len(alerts))

    def started_test(self):
        # Process should daemonize itself.
        if not self._sent:
            self._sent = True
            self.debug("stdin for send_nsca process:\n %r", self._body)
            self._control.transport.write(self._body)
            self._control.transport.closeStdin()

        return True
