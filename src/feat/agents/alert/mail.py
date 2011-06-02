import smtplib
from email.mime.text import MIMEText

from zope.interface import implements, classProvides

from feat.agents.base import replay, labour
from feat.common import serialization

from feat.agents.alert.interface import *


@serialization.register
class Labour(labour.BaseLabour):

    classProvides(IEmailSenderLabourFactory)
    implements(IAlertSenderLabour)

    @replay.side_effect
    def send(self, config, msg_body, severity):
        config = config.mail_config
        msg_body = '[Alert %s] %s' % (severity.name, msg_body)
        server = smtplib.SMTP(config.SMTP)
        server.starttls()
        server.login(config.username, config.password)
        msg = MIMEText(msg_body)
        msg['Subject'] = msg_body
        msg['From'] = config.fromaddr
        msg['To'] = config.toaddrs
        server.sendmail(config.fromaddr, config.toaddrs, msg.as_string())
        server.quit()
