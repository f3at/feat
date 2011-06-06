from zope.interface import implements, classProvides

from feat.agencies import periodic
from feat.agents.base import replay, collector, labour, task
from feat.common import serialization

from feat.agents.monitor.interface import *
from feat.interface.protocols import *


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
        self.last_state = PatientState.alive
        self.state = PatientState.alive
        self.counter = 0

    def beat(self, beat_time):
        self.counter += 1
        if beat_time > self.last_beat:
            self.last_beat = beat_time

    def check(self, ref_time):
        delta = ref_time - self.last_beat
        if delta > self.period:
            if delta > (self.max_skip * self.period):
                state = PatientState.dead
            elif delta > (1.5 * self.period):
                state = PatientState.dying
            else:
                state = PatientState.alive
        else:
            state = PatientState.alive

        self.last_state, self.state = self.state, state

        return self.last_state, self.state


@serialization.register
class HeartMonitor(labour.BaseLabour):

    classProvides(IHeartMonitorFactory)
    implements(IHeartMonitor)

    log_category = "heart-monitor"

    def __init__(self, doctor, check_period=None):
        labour.BaseLabour.__init__(self, IDoctor(doctor))
        self._patients = {}
        self._check_period = check_period or DEFAULT_CHECK_PERIOD
        self._next_check = None
        self._task = None

    ### Public Methods ###

    @replay.side_effect
    def beat(self, agent_id, instance_id):
        key = (agent_id, instance_id)
        if key in self._patients:
            self._patients[key].beat(self.patron.get_time())

    ### IHeartMonitor Methods ###

    @replay.side_effect
    def startup(self):
        self.resume()

    @replay.side_effect
    def cleanup(self):
        self.pause()

    @replay.side_effect
    def pause(self):
        if self._task:
            self._task.cancel()
            self._task = None

    @replay.side_effect
    def resume(self):
        if self._task is None:
            agent = self.patron
            agent.register_interest(HeartBeatCollector, self)
            self._task = agent.initiate_protocol(CheckPatientTask, self,
                                                 self._check_period)

    @replay.side_effect
    def add_patient(self, agent_id, instance_id, payload=None,
                    period=None, max_skip=None):
        self.debug("Start agent's %s/%s heart monitoring",
                   agent_id, instance_id)
        key = (agent_id, instance_id)
        patient = Patient(agent_id, instance_id, payload,
                          self.patron.get_time(), period, max_skip)
        self._patients[key] = patient

    @replay.side_effect
    def remove_patient(self, agent_id, instance_id):
        key = (agent_id, instance_id)
        if key in self._patients:
            self.debug("Stop agent's %s/%s heart monitoring",
                       agent_id, instance_id)
            del self._patients[key]

    def check_patients(self):
        dead_patients = []
        ref_time = self.patron.get_time()
        for patient in self._patients.itervalues():
            agent_id = patient.agent_id
            instance_id = patient.instance_id
            payload = patient.payload
            before, after = patient.check(ref_time)
            if before == after:
                continue
            if after is PatientState.dying:
                self.warning("Agent %s/%s heart not responding",
                             agent_id, instance_id)
                continue
            if after is PatientState.dead:
                self.patron.on_heart_failed(agent_id, instance_id, payload)
                dead_patients.append(patient)
        for patient in dead_patients:
            self.remove_patient(patient.agent_id, patient.instance_id)

    def iter_patients(self):
        return self._patients.itervalues()

    ### Private Methods ###

    def _periodic_check(self):
        self.check_patients()
        self._schedule_check()

    def _schedule_check(self):
        self._cancel_check()
        cid = self.patron.call_later(self._check_period, self._periodic_check)
        self._next_check = cid

    def _cancel_check(self):
        if self._next_check is not None:
            self.patron.cancel_delayed_call(self._next_check)
        self._next_check = None


class CheckPatientTask(task.StealthPeriodicTask):

    protocol_id = "monitor_agent:check-patient"

    def initiate(self, monitor, period):
        self._monitor = monitor
        return task.StealthPeriodicTask.initiate(self, period)

    def run(self):
        self._monitor.check_patients()


class HeartBeatCollector(collector.BaseCollector):

    protocol_id = "heart-beat"
    interest_type = InterestType.private

    @replay.mutable
    def initiate(self, state, monitor):
        state.monitor = monitor

    @replay.immutable
    def notified(self, state, msg):
        agent_id, instance_id = msg.payload
        self.log("Hard beat received from agent %s/%s",
                 agent_id, instance_id)
        state.monitor.beat(agent_id, instance_id)
