from zope.interface import implements, classProvides

from feat.agents.base import replay, labour
from feat.common import serialization

from feat.agents.alert.interface import *


@serialization.register
class MailLabour(labour.BaseLabour):

    classProvides(IEmailSenderLabourFactory)
    implements(IAlertSenderLabour)

    @replay.side_effect
    def send(self, config, msg, severity):
        """Nothing"""


@serialization.register
class NagiosLabour(labour.BaseLabour):

    classProvides(INagiosSenderLabourFactory)
    implements(IAlertSenderLabour)

    @replay.side_effect
    def send(self, config, msg, severity):
        """Nothing"""
