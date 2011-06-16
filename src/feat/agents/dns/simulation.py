from zope.interface import implements, classProvides

from feat.agents.base import replay, labour
from feat.common import serialization

from feat.agents.dns.interface import *


@serialization.register
class Labour(labour.BaseLabour):

    classProvides(IDNSServerLabourFactory)
    implements(IDNSServerLabour)

    def __init__(self, patron, resolver, slaves, suffix):
        labour.BaseLabour.__init__(self, patron)

    @replay.side_effect
    def initiate(self):
        """Nothing."""

    @replay.side_effect
    def startup(self, port):
        return True

    def cleanup(self):
        """Nothing."""

    def notify_slaves(self):
        """Nothing."""
