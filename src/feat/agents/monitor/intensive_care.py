# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.
from zope.interface import implements, classProvides

from feat.agents.base import replay, collector, labour, task
from feat.agents.application import feat

from feat.agents.monitor.interface import (
    IPatientStatus, DEFAULT_HEARTBEAT_PERIOD, DEFAULT_DYING_SKIPS,
    DEFAULT_DEATH_SKIPS, PatientState, IIntensiveCare,
    IIntensiveCareFactory, IAssistant, IDoctor, DEFAULT_CONTROL_PERIOD)
from feat.interface.protocols import InterestType
from feat.interface.recipient import IRecipient

PATIENT_RESET_EXTRA = 2/3.0


class Patient(object):

    implements(IPatientStatus)

    def __init__(self, recipient, location, beat_time,
                 period=None, dying_skips=None,
                 death_skips=None, patient_type=None):
        self.patient_type = patient_type
        self.recipient = recipient
        self.location = location
        self.period = period or DEFAULT_HEARTBEAT_PERIOD
        self.dying_skips = dying_skips or DEFAULT_DYING_SKIPS
        self.death_skips = death_skips or DEFAULT_DEATH_SKIPS
        self.last_state = PatientState.alive
        self.state = PatientState.alive
        self.reset(beat_time, 0)

        assert self.dying_skips <= self.death_skips, \
               "Death skips should be bigger than dying skips"

    def reset(self, beat_time, extra=PATIENT_RESET_EXTRA):
        # Reset to beat time plus 2/3 of a period to reduce false death
        self.last_beat = beat_time + self.period * extra
        self.counter = 0

    def beat(self, beat_time):
        self.counter += 1
        if beat_time > self.last_beat:
            self.last_beat = beat_time

    def check(self, ref_time):
        delta = ref_time - self.last_beat
        if delta > self.period:
            if delta > (self.death_skips * self.period):
                state = PatientState.dead
            elif delta > (self.dying_skips * self.period):
                state = PatientState.dying
            else:
                state = PatientState.alive
        else:
            state = PatientState.alive

        self.last_state, self.state = self.state, state

        return self.last_state, self.state


@feat.register_restorator
class IntensiveCare(labour.BaseLabour):

    classProvides(IIntensiveCareFactory)
    implements(IIntensiveCare)

    def __init__(self, assistant, doctor, control_period=None):
        labour.BaseLabour.__init__(self, IAssistant(assistant))
        self._doctor = IDoctor(doctor)
        self._patients = {} # {AGENT_ID: Patient}
        self._control_period = control_period or DEFAULT_CONTROL_PERIOD
        self._task = None
        self._last_check_epoch = None
        self._skip_checks = None

    ### Public Methods ###

    @replay.side_effect
    def beat(self, agent_id):
        if agent_id in self._patients:
            self._patients[agent_id].beat(self.patron.get_time())

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
            beat_time = agent.get_time()
            for patient in self._patients.itervalues():
                patient.reset(beat_time)
            agent.register_interest(HeartBeatCollector, self)
            self._task = agent.initiate_protocol(CheckPatientTask, self,
                                                 self._control_period)

    @replay.side_effect
    def has_patient(self, identifier):
        if IRecipient.providedBy(identifier):
            identifier = identifier.key
        return identifier in self._patients

    @replay.side_effect
    def add_patient(self, recipient, location,
                    period=None, dying_skips=None,
                    death_skips=None, patient_type=None):
        agent_id = recipient.key
        assert agent_id not in self._patients, \
               "Patient already added to intensive care"
        self.debug("Start agent's %s heart monitoring", agent_id)

        patient = Patient(recipient, location, self.patron.get_time(),
                          period=period, dying_skips=dying_skips,
                          death_skips=death_skips, patient_type=patient_type)
        self._patients[agent_id] = patient
        self._doctor.on_patient_added(patient)

    @replay.side_effect
    def remove_patient(self, identifier):
        if IRecipient.providedBy(identifier):
            identifier = identifier.key
        if identifier in self._patients:
            self.debug("Stop agent's %s heart monitoring", identifier)
            patient = self._patients[identifier]
            self._doctor.on_patient_removed(patient)
            del self._patients[identifier]

    def check_patients(self):
        ref_time = self.patron.get_time()

        # Detect wakeup from the suspend
        if (self._last_check_epoch is not None and
            ref_time - self._last_check_epoch > 2 * self._control_period):
            # when this happens skip checking patient state for 3 runs
            self.info("Detected monitor wakeup, I will skip next 3 checks")
            self._skip_checks = 3

        self._last_check_epoch = ref_time

        if self._skip_checks:
            self._skip_checks -= 1
            self.debug("Skipping check of intensive care, %d left to skip",
                       self._skip_checks)
            return

        for patient in self._patients.itervalues():
            recipient = patient.recipient
            agent_id = recipient.key
            before, after = patient.check(ref_time)

            if before == after:
                continue

            if before == PatientState.alive:
                if after == PatientState.dying:
                    self.log("Agent %s heart not responding", agent_id)
                    self._doctor.on_patient_dying(patient)
                    continue

            if after == PatientState.dead:
                self.log("Agent %s heart failed", agent_id)
                self._doctor.on_patient_died(patient)
                continue

            if after == PatientState.alive:
                self.log("Agent %s heart restarted", agent_id)
                self._doctor.on_patient_resurrected(patient)
                continue

    def get_patient(self, identifier):
        if IRecipient.providedBy(identifier):
            identifier = identifier.key
        return self._patients.get(identifier)

    def iter_patients(self):
        return self._patients.itervalues()


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
        agent_id, _time, index = msg.payload
        self.log("Heartbeat %s received from agent %s", index, agent_id)
        state.monitor.beat(agent_id)
