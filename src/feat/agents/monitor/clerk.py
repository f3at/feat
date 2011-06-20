from zope.interface import implements, classProvides

from feat.agents.base import replay, labour
from feat.common import serialization, error

from feat.agents.monitor.interface import *
from feat.interface.protocols import *
from feat.interface.recipient import *


class Location(object):

    implements(ILocationStatus)

    def __init__(self, clerk, name):
        self._clerk = clerk

        self.name = name
        self.state = LocationState.normal

        self._patients = {} # {AGENT_ID: PatientStatus}

    ### ILocationStatus ###

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
        return len(self._patients) == 0

    def _patient_dying(self, patient):
        pass

    def _patient_died(self, patient):
        self._clerk._patient_dead(patient)

    def _patient_resurected(self, patient):
        pass


@serialization.register
class Clerk(labour.BaseLabour):

    classProvides(IClerkFactory)
    implements(IClerk, IDoctor)

    def __init__(self, assistant, coroner):
        labour.BaseLabour.__init__(self, IAssistant(assistant))
        self._coroner = ICoroner(coroner)

        self._locations = {} # {LOCATION_NAME: Location}
        self._patients = {} # {AGENT_ID: Location}

    ### IClerk ###

    def startup(self):
        pass

    def cleanup(self):
        pass

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
            location = Location(self, patient.location)
            self._locations[location] = location

        location._add_patient(patient)
        self._patients[agent_id] = location

    def on_patient_removed(self, patient):
        agent_id = patient.recipient.key

        if agent_id in self._patients:
            del self._patients[agent_id]

        location = self._locations.get(patient.location)
        if location:
            if not location._remove_patient(patient):
                del self._locations[patient.location]

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
