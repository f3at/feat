from zope.interface import implements, classProvides

from feat.agents.base import replay, labour
from feat.common import serialization

from feat.agents.alert.interface import *


@serialization.register
class Labour(labour.BaseLabour):

    classProvides(IEmailSenderLabourFactory)
    implements(IEmailSenderLabour)

    @replay.side_effect
    def send(self, config, msg):
        """Nothing"""
