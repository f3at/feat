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

from feat.agents.base import replay, labour
from feat.common import error
from feat.agents.application import feat

from feat.agents.monitor.interface import *
from feat.interface.protocols import *
from feat.interface.recipient import *
from feat.database.interface import *


class Location(object):

    implements(ILocationStatus)

    def __init__(self, clerk, name, enable_quarantine=True):
        self._clerk = clerk
        self._quarantine_enabled = enable_quarantine

        self.name = name
        self.state = LocationState.normal

        self._paused = False
        self._patients = {} # {AGENT_ID: PatientStatus}
        self._dead = set() # set([AGENT_ID])

    ### ILocationStatus ###

    def get_patient(self, identifier):
        if IRecipient.providedBy(identifier):
            identifier = identifier.key
        return self._patients.get(identifier)

    def iter_patients(self, state=None):
        return (p for p in self._patients.itervalues()
                if state is None or p.state is state)

    def count_patients(self, state=None):
        return len(list(self.iter_patients(state)))

    def count_alive(self):
        return self.count_patients(PatientState.alive)

    def count_dying(self):
        return self.count_patients(PatientState.dying)

    def count_dead(self):
        return self.count_patients(PatientState.dead)

    def get_recovery_time(self):
        return max(p.period for p in self._patients.itervalues())

    ### protected ###

    def _add_patient(self, patient):
        agent_id = patient.recipient.key
        assert agent_id not in self._patients, \
               "Patient already added to location"
        self._patients[agent_id] = patient

    def _remove_patient(self, patient):
        agent_id = patient.recipient.key
        if agent_id in self._patients:
            del self._patients[agent_id]
        if agent_id in self._dead:
            self._dead.remove(agent_id)

        if (self._quarantine_enabled
            and self.state is LocationState.normal
            and patient.state is not PatientState.dead):
            self._check_quarantine()

        return len(self._patients) == 0

    def _patient_dying(self, patient):
        assert patient.recipient.key in self._patients, \
               "Unknown patient dying"

    def _patient_died(self, patient):
        assert patient.recipient.key in self._patients, \
               "Unknown patient died"

        if not self._quarantine_enabled:
            self._notify_death(patient)
            return

        if self.state is LocationState.normal:
            alive = self.count_alive()
            if alive > 0:
                # There is alive agents around so this one must really be dead
                self._notify_death(patient)
                return

        self._check_quarantine()

    def _patient_resurrected(self, patient):
        agent_id = patient.recipient.key
        assert agent_id in self._patients, \
               "Unknown patient resurrected"

        if agent_id in self._dead:
            # not dead anymore, so cleanup notification flag
            # for if it dies again later
            self._dead.remove(agent_id)

        if not self._quarantine_enabled:
            return

        if self.state is LocationState.recovering:
            dying = self.count_dying()
            dead = self.count_dead()
            if dying == 0 and dead == 0:
                # Everything got recovered, not recovering anymore
                self._set_state(LocationState.normal)
            return

        if self.state in (LocationState.isolated, LocationState.normal):
            # We were in normal state and some agent got resurrected,
            # or we were isolated, and  need to lift the quarantine
            dying = self.count_dying()
            dead = self.count_dead()
            if dying == 0 and dead == 0:
                # Everything got recovered, not recovering anymore
                self._set_state(LocationState.normal)
                return

            self._set_state(LocationState.recovering)
            if self._paused:
                # We are paused, do not ask for the quarantine to be lifted
                return
            self._clerk._location_recovering(self)
            return

    def _pause(self):
        self._paused = True
        if self.state is LocationState.recovering:
            # Got paused, quarantine will never be lifted, so go back to normal
            self._set_state(LocationState.normal)

    def _resume(self):
        self._paused= False

        if not self._quarantine_enabled:
            # Quarantine not enabled, just count the dead
            self._bring_out_your_dead()
            return

        if self.state is LocationState.isolated:
            # We were or got isolated, ask for quarantine
            self._clerk._need_quarantine(self)
            return

        if self.state is LocationState.recovering:

            self._clerk._location_recovering(self)

    def _start_quarantine(self):
        if self.state is not LocationState.isolated:
            self._set_state(LocationState.isolated)

    def _start_recovery(self):
        if self.count_dead() > 0 or self.count_dying() > 0:
            if self.state is not LocationState.recovering:
                self._set_state(LocationState.recovering)
            return max(p.period for p in self._patients.itervalues()
                       if p.state is not PatientState.alive)
        return 0

    def _quarantine_lifted(self):
        self._set_state(LocationState.normal)
        self._bring_out_your_dead()

    ### private ###

    def _set_state(self, state):
        self.state = state
        self._clerk._location_state_changed(self)

    def _notify_death(self, patient):
        if self._paused:
            # We are paused, do not notify any death
            return

        agent_id = patient.recipient.key
        if agent_id not in self._dead:
            self._dead.add(agent_id)
            self._clerk._patient_dead(patient)

    def _bring_out_your_dead(self):
        for patient in list(self.iter_patients(PatientState.dead)):
            self._notify_death(patient)

    def _check_quarantine(self):
        if self.count_dying() > 0:
            # Some agents are dying around, waiting for them to settle
            return

        if not self.count_dead() > 0:
            # Nobodies dead, why did you call me ?
            return

        # All agent on this host seems dead, put the host in quarantine
        if self.state != LocationState.isolated:
            self._set_state(LocationState.isolated)

            if self._paused:
                # We are paused, so don't ask for quarantine
                return

            self._clerk._need_quarantine(self)
            return


@feat.register_restorator
class Clerk(labour.BaseLabour):

    classProvides(IClerkFactory)
    implements(IClerk, IDoctor)

    def __init__(self, assistant, coroner,
                 location="localhost", enable_quarantine=True,
                 host_quarantine_length=DEFAULT_HOST_QUARANTINE_LENGTH,
                 self_quarantine_length=DEFAULT_SELF_QUARANTINE_LENGTH):
        labour.BaseLabour.__init__(self, IAssistant(assistant))
        self._coroner = ICoroner(coroner)

        self._locations = {} # {LOCATION_NAME: Location}
        self._patients = {} # {AGENT_ID: Location}
        self._location_calls = {} # {LOCATION_NAME: CALL_ID}
        self._isolated_call = None
        self._quarantine_enabled = enable_quarantine
        self._location = location
        self._state = MonitorState.normal
        self._host_quarantine_length = host_quarantine_length
        self._self_quarantine_length = self_quarantine_length

    ### IClerk ###

    @property
    def state(self):
        return self._state

    @property
    def location(self):
        return self._location

    def startup(self):
        pass

    def cleanup(self):
        pass

    @replay.side_effect
    def on_disconnected(self):
        if self._state is not MonitorState.disconnected:
            # We got disconnected, pause all location monitoring
            self._iso_cancel_call()
            self._state = MonitorState.disconnected
            self._loc_pause_all()

    @replay.side_effect
    def on_reconnected(self):
        if self._state is MonitorState.disconnected:
            # We are connected back, resume all location monitoring
            self._state = MonitorState.normal
            self._loc_resume_all()
            self._check_isolated()

    @replay.side_effect
    def has_patient(self, identifier):
        if IRecipient.providedBy(identifier):
            identifier = identifier.key
        return identifier in self._patients

    def get_patient(self, identifier):
        if IRecipient.providedBy(identifier):
            identifier = identifier.key
        location = self._patients.get(identifier)
        if location:
            return location.get_patient(identifier)

    def get_location(self, location):
        return self._locations.get(location)

    def iter_locations(self):
        return self._locations.itervalues()

    ### IDoctor ###

    def on_patient_added(self, patient):
        agent_id = patient.recipient.key
        assert agent_id not in self._patients, \
               "Patient already checked in"

        location = self._locations.get(patient.location)
        if not location:
            location = Location(self, patient.location,
                                self._quarantine_enabled)
            self._locations[patient.location] = location

        location._add_patient(patient)
        self._patients[agent_id] = location

    def on_patient_removed(self, patient):
        agent_id = patient.recipient.key

        if agent_id in self._patients:
            del self._patients[agent_id]

        location = self._locations.get(patient.location)
        if location:
            if location._remove_patient(patient):
                del self._locations[location.name]

    def on_patient_dying(self, patient):
        location = self._patients[patient.recipient.key]
        location._patient_dying(patient)

    def on_patient_died(self, patient):
        location = self._patients[patient.recipient.key]
        location._patient_died(patient)

    def on_patient_resurrected(self, patient):
        location = self._patients[patient.recipient.key]
        location._patient_resurrected(patient)

    ### protected ###

    def _patient_dead(self, patient):
        self.debug("Patient %s definitely dead, calling the coroner",
                   patient.recipient.key)
        self._coroner.on_patient_dead(patient)

    def _location_state_changed(self, location):
        """Called by locations when there state change, even when paused."""
        if location.state is LocationState.normal:
            # If the location got back to normal cancel any pending call
            self._loc_cancel_call(location)
        if self._state is MonitorState.isolated:
            # If we were isolated and any location other than our own
            # is not isolated anymore, it mean we got out of isolation
            if location.state is not LocationState.isolated:
                if location.name != self._location:
                    self._state = MonitorState.normal
                    self._iso_cancel_call()
                    self._loc_resume_all()
        elif self._state is MonitorState.recovering:
            # If we were recovering and all locations state
            # is back to normal it mean we recovered
            if not [l for l in self._locations.itervalues()
                    if l.state is not LocationState.normal]:
                self._state = MonitorState.normal

    def _need_quarantine(self, location):
        """Called by locations when it detects it need to be quarantined."""
        self._loc_start_quarantine(location)
        if self._state is not MonitorState.isolated:
            self._loc_schedule_lift(location)

    def _location_recovering(self, location):
        """called by locations is recovering and any quarantine can be lifted,
        or after resuming while the location is currently recovering."""
        self._loc_start_recovery(location)

    ### private ###

    def _loc_pause_all(self):
        for loc in self._locations.itervalues():
            self._loc_cancel_call(loc)
            loc._pause()

    def _loc_resume_all(self):
        for loc in self._locations.itervalues():
            loc._resume()

    def _loc_schedule_call(self, delay, function, location):
        """Schedule a call for the specified location,
        will cancel and override any previous call."""
        self._loc_cancel_call(location)
        call_id = self.patron.call_later(delay, function, location)
        self._location_calls[location.name] = call_id

    def _loc_cancel_call(self, location):
        """Cancel the current call for the specified location."""
        if location.name in self._location_calls:
            call_id = self._location_calls[location.name]
            if call_id is not None:
                self.patron.cancel_delayed_call(call_id)
        self._loc_cleanup_call(location)

    def _loc_cleanup_call(self, location):
        """Cleanup the current call for the specified location
        WITHOUT CANCELING IT."""
        if location.name in self._location_calls:
            del self._location_calls[location.name]

    def _loc_start_quarantine(self, location):
        if not self._check_isolated():
            self._loc_cancel_call(location)
            location._start_quarantine()

    def _loc_schedule_lift(self, location):
        self._loc_schedule_call(self._host_quarantine_length,
                                self._loc_lift_quarantine, location)

    def _loc_start_recovery(self, location):
        # At least one patient resurrected, wait extra time
        # to let the others a chance to resurrect too
        recovery_time = location._start_recovery()
        self._loc_schedule_call(recovery_time,
                                self._loc_lift_quarantine, location)

    def _loc_lift_quarantine(self, location):
        location._quarantine_lifted()

    def _check_isolated(self):
        if self._state in (MonitorState.isolated, MonitorState.recovering):
            return True

        for loc in self._locations.itervalues():
            if loc.state is not LocationState.isolated:
                if loc.name != self._location:
                    # Some other location is alive
                    if loc.count_alive() > 0:
                        # And it does have patient alive
                        return False

        # The monitor itself may be isolated from the outside world
        # pause monitoring and wait some time for for the problem
        # to be resolved.
        self._state = MonitorState.isolated
        self._iso_schedule_call(self._self_quarantine_length,
                                self._iso_lift_quarantine)
        self._loc_pause_all()
        return True

    def _iso_cancel_call(self):
        if self._isolated_call is not None:
            self.patron.cancel_delayed_call(self._isolated_call)
            self._isolated_call = None

    def _iso_schedule_call(self, time, fun, *args, **kwargs):
        self._iso_cancel_call()
        call_id = self.patron.call_later(time, fun, *args, **kwargs)
        self._isolated_call = call_id

    def _iso_lift_quarantine(self):
        # There is nothing more to do, we cannot wait forever
        self._state = MonitorState.recovering
        self._loc_resume_all()
