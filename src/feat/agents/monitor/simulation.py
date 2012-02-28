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
from feat.agents.application import feat

from feat.agents.monitor.interface import *
from feat.interface.agent import *
from feat.interface.recipient import *
from feat.interface.task import *


class Location(object):

    implements(ILocationStatus)

    def __init__(self, name):
        self.name = name
        self.state = LocationState.normal

        self._patients = {} # {IRecipient: Patient}

    ### ILocationStatus ###

    def has_patient(self, identifier):
        if IRecipient.providedBy(identifier):
            identifier = identifier.key
        return identifier in self._patients

    def get_patient(self, identifier):
        if IRecipient.providedBy(identifier):
            identifier = identifier.key
        return self._patients.get(identifier)

    def iter_patients(self):
        return self._patients.itervalues()

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
        return len(self._patients)


class Patient(object):

    implements(IPatientStatus)

    def __init__(self, recipient, location,
                 period=None, dying_skips=None,
                 death_skips=None, patient_type=None):
        self.patient_type = patient_type
        self.location = location
        self.recipient = recipient
        self.state = PatientState.alive
        self.counter = 0

        self.period = period
        self.dying_skips = dying_skips
        self.death_skips = death_skips


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
        self._patients = {} # {AGENT_ID: Patient}

    ### IClerk ###

    def startup(self):
        """Nothing."""

    def cleanup(self):
        """Nothing."""

    @replay.side_effect
    def on_disconnected(self):
        pass

    @replay.side_effect
    def on_reconnected(self):
        pass

    @replay.side_effect
    def has_patient(self, identifier):
        if IRecipient.providedBy(identifier):
            identifier = identifier.key
        return self._patients.get(identifier)

    def get_patient(self, identifier):
        if IRecipient.providedBy(identifier):
            identifier = identifier.key
        return self._patients.get(identifier)

    def get_location(self, location):
        return self._locations.get(location)

    def iter_locations(self):
        return self._locations.itervalues()

    ### IDoctor ###

    @replay.side_effect
    def on_patient_added(self, patient):
        agent_id = patient.recipient.key
        assert agent_id not in self._patients, \
               "Patient already checked in"
        self._patients[agent_id] = patient
        self._add_to_location(patient)

    @replay.side_effect
    def on_patient_removed(self, patient):
        agent_id = patient.recipient.key
        if agent_id in self._patients:
            del self._patients[agent_id]
            loc = self._locations[patient.location]
            if not loc._remove_patient(patient):
                del self._locations[patient.location]

    def on_patient_dying(self, recipient):
        """Nothing."""

    def on_patient_died(self, recipient):
        """Nothing."""

    def on_patient_resurrected(self, recipient):
        """Nothing."""

    ### private ###

    def _add_to_location(self, patient):
        location = patient.location
        if location not in self._locations:
            self._locations[location] = Location(location)
        self._locations[location]._add_patient(patient)


@feat.register_restorator
class IntensiveCare(labour.BaseLabour):

    classProvides(IIntensiveCareFactory)
    implements(IIntensiveCare)

    def __init__(self, assistant, doctor, control_period=None):
        labour.BaseLabour.__init__(self, IAssistant(assistant))
        self._doctor = IDoctor(doctor)
        self._patients = {}

    @replay.side_effect
    def startup(self):
        """Nothing."""

    @replay.side_effect
    def cleanup(self):
        """Nothing."""

    @replay.side_effect
    def pause(self):
        """Nothing."""

    @replay.side_effect
    def resume(self):
        """Nothing."""

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
        patient = Patient(recipient, location, patient_type=patient_type)
        self._patients[recipient.key] = patient
        self._doctor.on_patient_added(patient)

    @replay.side_effect
    def remove_patient(self, identifier):
        if IRecipient.providedBy(identifier):
            identifier = identifier.key
        if identifier in self._patients:
            patient = self._patients[identifier]
            self._doctor.on_patient_removed(patient)
            del self._patients[identifier]

    @replay.side_effect
    def control_patients(self):
        """Does nothing."""

    def get_patient(self, identifier):
        if IRecipient.providedBy(identifier):
            identifier = identifier.key
        return self._patients.get(identifier)

    def iter_patients(self):
        return self._patients.itervalues()
