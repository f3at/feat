from zope.interface import implements, classProvides

from feat.agents.base import replay, labour
from feat.common import serialization

from feat.agents.monitor.interface import *
from feat.interface.agent import *
from feat.interface.task import *


class Patient(object):

    implements(IPatient)

    def __init__(self, agent_id, instance_id, payload,
                 beat_time, period=None, max_skip=None):
        self.agent_id = agent_id
        self.instance_id = instance_id
        self.payload = payload
        self.period = period or DEFAULT_HEARTBEAT_PERIOD
        self.max_skip = max_skip or DEFAULT_MAX_SKIPPED_HEARTBEAT
        self.last_beat = beat_time
        self.state = PatientState.alive
        self.counter = 0


@serialization.register
class HeartMonitor(labour.BaseLabour):

    classProvides(IHeartMonitorFactory)
    implements(IHeartMonitor)

    log_category = "heart-monitor"

    def __init__(self, doctor):
        labour.BaseLabour.__init__(self, IDoctor(doctor))
        self._patients = {}

    @replay.side_effect
    def startup(self):
        """Does nothing."""

    @replay.side_effect
    def cleanup(self):
        """Does nothing."""

    @replay.side_effect
    def pause(self):
        pass

    @replay.side_effect
    def resume(self):
        pass

    @replay.side_effect
    def add_patient(self, agent_id, instance_id, payload=None,
                    period=None, max_skip=None):
        key = (agent_id, instance_id)
        patient = Patient(agent_id, instance_id, payload,
                          self.patron.get_time(), period, max_skip)
        self._patients[key] = patient

    @replay.side_effect
    def remove_patient(self, agent_id, instance_id):
        key = (agent_id, instance_id)
        if key in self._patients:
            del self._patients[key]

    @replay.side_effect
    def check_patients(self):
        """Does nothing."""

    def iter_patients(self):
        return self._patients.itervalues()
