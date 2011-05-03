from zope.interface import implements, classProvides

from feat.agents.base import replay, labour
from feat.common import serialization

from feat.agents.monitor.interface import *
from feat.interface.agent import *
from feat.interface.task import *


@serialization.register
class HeartMonitor(labour.BaseLabour):

    classProvides(IHeartMonitorFactory)
    implements(IHeartMonitor)

    log_category = "heart-monitor"

    def __init__(self, doctor):
        labour.BaseLabour.__init__(self, IDoctor(doctor))

    @replay.side_effect
    def initiate(self):
        """Does nothing."""

    @replay.side_effect
    def cleanup(self):
        """Does nothing."""

    @replay.side_effect
    def add_patient(self, agent_id, instance_id, period=None):
        """Does nothing."""

    @replay.side_effect
    def remove_patient(self, agent_id, instance_id):
        """Does nothing."""

    @replay.side_effect
    def check_patients(self):
        """Does nothing."""
