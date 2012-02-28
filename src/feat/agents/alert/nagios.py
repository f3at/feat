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
import commands

from zope.interface import implements, classProvides

from feat.agents.base import replay, alert
from feat.common import log, serialization

from feat.agents.alert.interface import *
from feat.agents.application import feat


CODES = {alert.Severity.recover: 0,
         alert.Severity.low: 1,
         alert.Severity.medium: 1,
         alert.Severity.high: 2}


@feat.register_restorator
class Labour(log.Logger, serialization.Serializable):

    classProvides(INagiosSenderLabourFactory)
    implements(IAlertSenderLabour)

    @replay.side_effect
    def send(self, config, msg_body, severity):
        config = config.nagios_config
        self.log('I am about to send an alert to nagios')

        return_code = CODES.get(severity, 1)

        cmd = "%s -H %s -c %s -d ';'" % (config.send_nsca,
                                         config.monitor,
                                         config.config_file)

        msg = "'%s;%s;%s;%s\n'" % (config.host, config.svc_descr,
                                   return_code, msg_body)

        cmd = 'echo -e  %s | %s' % (msg, cmd)
        self.log('Send alert to nagios: %s' % cmd)
        status, output = commands.getstatusoutput(cmd)
        if status != 0:
            self.warning('Got error: %d (%s)', status, output)
