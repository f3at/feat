from zope.interface import implements, classProvides

from feat.agents.base import replay
from feat.common import serialization

from feat.agents.dns.labour import *


@serialization.register
class Labour(serialization.Serializable, EqualityMixin):

    classProvides(IDNSServerLabourFactory)
    implements(IDNSServerLabour)

    def __init__(self, patron):
        """Nothing."""

    @replay.side_effect
    def initiate(self):
        """Nothing."""

    @replay.side_effect
    def startup(self, port):
        return True

    def cleanup(self):
        """Nothing."""
