import smtplib
from email.mime.text import MIMEText

from zope.interface import implements, classProvides

from feat.agents.base import replay, labour
from feat.common import defer, serialization, log

from feat.agents.alert.interface import *


@serialization.register
class Labour(labour.BaseLabour):

    classProvides(IEmailSenderLabourFactory)
    implements(IEmailSenderLabour)

    def __init__(self, logger):
        log.Logger.__init__(self, logger)

    def __eq__(self, other):
        if isinstance(other, type(self)):
            return True
        return NotImplemented

    def __ne__(self, other):
        if isinstance(other, type(self)):
            return False
        return NotImplemented

    ### ISerializable Methods ###

    def snapshot(self):
        """Nothing to serialize."""

    def recover(self, snapshot):
        """Nothing to recover."""

    @replay.side_effect
    def send(self, config, msg_body):
        server = smtplib.SMTP(config.SMTP)
        server.starttls()
        server.login(config.username, config.password)
        msg = MIMEText(msg_body)
        msg['Subject'] = msg_body
        msg['From'] = config.fromaddr
        msg['To'] = config.toaddrs
        server.sendmail(config.fromaddr, config.toaddrs, msg.as_string())
        server.quit()
