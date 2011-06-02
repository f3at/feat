import commands

from zope.interface import implements, classProvides

from feat.agents.base import replay, alert
from feat.common import log, serialization

from feat.agents.alert.interface import *


CODES = {alert.Severity.recover: 0,
         alert.Severity.low: 1,
         alert.Severity.medium: 1,
         alert.Severity.high: 2}


@serialization.register
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
