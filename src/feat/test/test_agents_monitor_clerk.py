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
import uuid

from zope.interface import implements

from feat.agencies.recipient import Recipient
from feat.agents.monitor.clerk import Location, Clerk

from feat.agents.monitor.interface import *
from feat.common import log, journal, time
from feat.interface.agent import *

from feat.test import common


class DummyPatient(object):

    implements(IPatientStatus)

    def __init__(self, recipient, location="localhost", period=3):
        self.recipient = recipient
        self.location = location
        self.period = period
        self.state = PatientState.alive


class DummyLocationPatient(DummyPatient):

    implements(IPatientStatus)

    def __init__(self, location, *args, **kwargs):
        DummyPatient.__init__(self, *args, **kwargs)
        self.location = location
        location._add_patient(self)

    def be_dying(self):
        self.state = PatientState.dying
        self.location._patient_dying(self)

    def die(self):
        self.state = PatientState.dead
        self.location._patient_died(self)

    def resurrect(self):
        self.state = PatientState.alive
        self.location._patient_resurrected(self)


class DummyDoctorPatient(DummyPatient):

    implements(IPatientStatus)

    def __init__(self, doctor, *args, **kwargs):
        DummyPatient.__init__(self, *args, **kwargs)
        self.doctor = doctor
        doctor.on_patient_added(self)

    def be_dying(self):
        self.state = PatientState.dying
        self.doctor.on_patient_dying(self)

    def die(self):
        self.state = PatientState.dead
        self.doctor.on_patient_died(self)

    def resurrect(self):
        self.state = PatientState.alive
        self.doctor.on_patient_resurrected(self)


class DummyClerk(object):

    def __init__(self):
        self.reset_all()

    def reset(self):
        self.dead = []

    def reset_all(self):
        self.quarantined = []
        self.recovering = []
        self.reset()

    def _location_state_changed(self, location):
        pass

    def _need_quarantine(self, location):
        self.quarantined.append(location)

    def _location_recovering(self, location):
        if location in self.quarantined:
            self.quarantined.remove(location)
        self.recovering.append(location)

    def _patient_dead(self, patient):
        self.dead.append(patient)


class DummyPatron(journal.DummyRecorderNode, log.LogProxy, log.Logger):

    implements(IAssistant, ICoroner)

    def __init__(self, logger, now=None):
        journal.DummyRecorderNode.__init__(self)
        log.LogProxy.__init__(self, logger)
        log.Logger.__init__(self, logger)
        self.calls = {} # {CALL_ID: (time, call_id, fun, args, kwargs)}
        self._call_index = 0
        self.reset()

    ### Public Methods ###

    def reset(self):
        self.dead = []

    def assertNoPendingCalls(self):
        if self.calls:
            raise AssertionError("No pending call expected")

    def assertCallNumber(self, expected):
        if len(self.calls) != expected:
            raise AssertionError("Expecting %d pending calls and got %s"
                                 % (expected, len(self.calls)))

    def has_call(self):
        return len(self.calls) > 0

    def next_call(self):
        if not self.calls:
            raise AssertionError("No pending call")

        calls = [(t, i, f, a, k, index)
                 for i, (t, f, a, k, index) in self.calls.items()]
        calls.sort(key=lambda x: (x[0], x[5]))
        _t, call_id, fun, args, kwargs, _index = calls.pop(0)
        del self.calls[call_id]

        fun(*args, **kwargs)

    ### IAssistant ###

    def initiate_protocol(self, factory, *args, **kwargs):
        raise NotImplementedError()

    def register_interest(self, factory, *args, **kwargs):
        raise NotImplementedError()

    def get_time(self):
        raise NotImplementedError()

    def call_later(self, delay, fun, *args, **kwargs):
        return self.call_later_ex(delay, fun, args, kwargs)

    def call_later_ex(self, delay, fun, args=(), kwargs={}, busy=True):
        # on 32-bit machines we can have
        # time.time() == time.time() evaluating to True
        # for this reason it's necessary to include call index to be able
        # to later sort in correctly according to the order of calls of
        # call_later()
        self._call_index += 1
        payload = (delay + time.time(), fun, args, kwargs, self._call_index)
        call_id = str(uuid.uuid1())
        self.calls[call_id] = payload
        return call_id

    def cancel_delayed_call(self, call_id):
        if call_id in self.calls:
            del self.calls[call_id]

    ### ICoroner ###

    def on_patient_dead(self, patient):
        self.dead.append(patient)


class TestClerk(common.TestCase):

    def assertLocState(self, clerk, name, state):
        self.assertEqual(clerk.get_location(name).state, state)

    def testSelfIsolation(self):
        patron = DummyPatron(self)
        clerk = Clerk(patron, patron, location="A")
        doctor = IDoctor(clerk)

        patient1 = DummyDoctorPatient(doctor, Recipient("AX"), location="A")
        patient2 = DummyDoctorPatient(doctor, Recipient("BX"), location="B")
        patient3 = DummyDoctorPatient(doctor, Recipient("BY"), location="B")

        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertEqual(patron.dead, [])
        patron.assertNoPendingCalls()

        patient2.be_dying()
        patient3.be_dying()
        patient2.die()
        patient3.die()

        self.assertEqual(clerk.state, MonitorState.isolated)
        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertLocState(clerk, "B", LocationState.isolated)
        patron.assertCallNumber(1)

        patient2.resurrect()

        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertLocState(clerk, "B", LocationState.recovering)
        patron.assertCallNumber(1)

        patient3.resurrect()

        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertLocState(clerk, "B", LocationState.normal)
        patron.assertNoPendingCalls()

        patient2.be_dying()
        patient3.be_dying()
        patient2.die()
        patient3.die()
        patient2.resurrect()

        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertLocState(clerk, "B", LocationState.recovering)
        self.assertEqual(patron.dead, [])
        patron.assertCallNumber(1)

        patron.next_call()

        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertEqual(patron.dead, [patient3])
        patron.assertNoPendingCalls()
        patron.reset()

        patient3.resurrect()
        patient2.be_dying()
        patient3.be_dying()
        patient2.die()
        patient3.die()

        self.assertEqual(clerk.state, MonitorState.isolated)
        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertLocState(clerk, "B", LocationState.isolated)
        patron.assertCallNumber(1)

        patron.next_call()

        self.assertEqual(clerk.state, MonitorState.recovering)
        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertLocState(clerk, "B", LocationState.isolated)
        patron.assertCallNumber(1)

        patient3.resurrect()

        self.assertEqual(clerk.state, MonitorState.recovering)
        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertLocState(clerk, "B", LocationState.recovering)
        patron.assertCallNumber(1)

        patient2.resurrect()

        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertLocState(clerk, "B", LocationState.normal)
        patron.assertNoPendingCalls()

        patient2.be_dying()
        patient3.be_dying()
        patient2.die()
        patient3.die()
        patron.next_call()
        patient3.resurrect()

        self.assertEqual(clerk.state, MonitorState.recovering)
        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertLocState(clerk, "B", LocationState.recovering)
        self.assertEqual(patron.dead, [])
        patron.assertCallNumber(1)

        patron.next_call()

        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertEqual(patron.dead, [patient2])
        patron.assertNoPendingCalls()
        patron.reset()

        patient2.resurrect()
        patient2.be_dying()
        patient3.be_dying()
        patient2.die()
        patient3.die()
        patron.next_call()

        self.assertEqual(clerk.state, MonitorState.recovering)
        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertLocState(clerk, "B", LocationState.isolated)
        patron.assertCallNumber(1)

        self.assertEqual(patron.dead, [])
        patron.next_call()

        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertEqual(patron.dead, [patient2, patient3])
        patron.assertNoPendingCalls()
        patron.reset()

        clerk.on_patient_removed(patient2)

        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertLocState(clerk, "B", LocationState.normal)
        patron.assertNoPendingCalls()

        clerk.on_patient_removed(patient3)

        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertEqual(clerk.get_location("B"), None)
        patron.assertNoPendingCalls()

    def testDisconnection(self):
        patron = DummyPatron(self)
        clerk = Clerk(patron, patron, location="A")
        doctor = IDoctor(clerk)

        patient1 = DummyDoctorPatient(doctor, Recipient("AX"), location="A")
        patient2 = DummyDoctorPatient(doctor, Recipient("BX"), location="B")
        patient3 = DummyDoctorPatient(doctor, Recipient("BY"), location="B")

        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertEqual(patron.dead, [])
        patron.assertNoPendingCalls()

        clerk.on_disconnected()

        self.assertEqual(clerk.state, MonitorState.disconnected)
        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertEqual(patron.dead, [])
        patron.assertNoPendingCalls()

        patient1.die()

        self.assertEqual(clerk.state, MonitorState.disconnected)
        self.assertLocState(clerk, "A", LocationState.isolated)
        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertEqual(patron.dead, [])
        patron.assertNoPendingCalls()

        patient2.die()

        self.assertEqual(clerk.state, MonitorState.disconnected)
        self.assertLocState(clerk, "A", LocationState.isolated)
        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertEqual(patron.dead, [])
        patron.assertNoPendingCalls()

        patient3.die()

        self.assertEqual(clerk.state, MonitorState.disconnected)
        self.assertLocState(clerk, "A", LocationState.isolated)
        self.assertLocState(clerk, "B", LocationState.isolated)
        self.assertEqual(patron.dead, [])
        patron.assertNoPendingCalls()

        clerk.on_reconnected()

        self.assertEqual(clerk.state, MonitorState.isolated)
        self.assertLocState(clerk, "A", LocationState.isolated)
        self.assertLocState(clerk, "B", LocationState.isolated)
        self.assertEqual(patron.dead, [])
        patron.assertCallNumber(1)

        # Going out of monitor isolation
        patient2.resurrect()

        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertLocState(clerk, "A", LocationState.isolated)
        self.assertLocState(clerk, "B", LocationState.recovering)
        self.assertEqual(patron.dead, [])
        patron.assertCallNumber(2)

        patient1.resurrect()

        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertLocState(clerk, "B", LocationState.recovering)
        self.assertEqual(patron.dead, [])
        patron.assertCallNumber(1)

        patient3.resurrect()

        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertEqual(patron.dead, [])
        patron.assertNoPendingCalls()

        patient2.be_dying()
        patient3.be_dying()
        patient2.die()
        patient3.die()

        self.assertEqual(clerk.state, MonitorState.isolated)
        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertLocState(clerk, "B", LocationState.isolated)
        self.assertEqual(patron.dead, [])
        patron.assertCallNumber(1)

        clerk.on_disconnected()

        self.assertEqual(clerk.state, MonitorState.disconnected)
        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertLocState(clerk, "B", LocationState.isolated)
        self.assertEqual(patron.dead, [])
        patron.assertNoPendingCalls()

        patient1.die()

        self.assertEqual(clerk.state, MonitorState.disconnected)
        self.assertLocState(clerk, "A", LocationState.isolated)
        self.assertLocState(clerk, "B", LocationState.isolated)
        self.assertEqual(patron.dead, [])
        patron.assertNoPendingCalls()

        patient3.resurrect()

        self.assertEqual(clerk.state, MonitorState.disconnected)
        self.assertLocState(clerk, "A", LocationState.isolated)
        self.assertLocState(clerk, "B", LocationState.recovering)
        self.assertEqual(patron.dead, [])
        patron.assertNoPendingCalls()

        clerk.on_reconnected()

        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertLocState(clerk, "A", LocationState.isolated)
        self.assertLocState(clerk, "B", LocationState.recovering)
        self.assertEqual(patron.dead, [])
        patron.assertCallNumber(2)

        patron.next_call()

        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertLocState(clerk, "A", LocationState.isolated)
        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertEqual(patron.dead, [patient2])
        patron.assertCallNumber(1)

        patron.next_call()

        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertEqual(patron.dead, [patient2, patient1])
        patron.assertNoPendingCalls()

    def testWithQuarantine(self):
        patron = DummyPatron(self)
        clerk = Clerk(patron, patron, location="C")
        doctor = IDoctor(clerk)

        patient1 = DummyDoctorPatient(doctor, Recipient("AX"), location="A")
        patient2 = DummyDoctorPatient(doctor, Recipient("BX"), location="B")
        patient3 = DummyDoctorPatient(doctor, Recipient("BY"), location="B")
        patient4 = DummyDoctorPatient(doctor, Recipient("CX"), location="C")
        patient5 = DummyDoctorPatient(doctor, Recipient("CY"), location="C")

        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(patron.dead, [])
        patron.assertNoPendingCalls()

        patient2.be_dying()

        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(patron.dead, [])
        patron.assertNoPendingCalls()

        # Just die right away because there is another patient alive
        patient2.die()

        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(patron.dead, [patient2])
        patron.assertNoPendingCalls()
        patron.reset()

        patient3.be_dying()

        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(patron.dead, [])
        patron.assertNoPendingCalls()

        # Put the location to quarantine because there is no patient alive
        patient3.die()

        self.assertLocState(clerk, "B", LocationState.isolated)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(patron.dead, [])
        patron.assertCallNumber(1)

        patient3.resurrect()

        self.assertLocState(clerk, "B", LocationState.recovering)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(patron.dead, [])
        patron.assertCallNumber(1)

        patient2.resurrect()

        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(patron.dead, [])
        patron.assertNoPendingCalls()

        patient2.be_dying()
        patient3.be_dying()
        patient2.die()

        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(patron.dead, [])
        patron.assertNoPendingCalls()

        patient3.resurrect()

        self.assertLocState(clerk, "B", LocationState.recovering)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(patron.dead, [])
        patron.assertCallNumber(1)

        patron.next_call()

        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(patron.dead, [patient2])
        patron.assertNoPendingCalls()
        patron.reset()

        patient2.resurrect()
        patient2.be_dying()
        patient3.be_dying()
        patient2.die()

        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(patron.dead, [])
        patron.assertNoPendingCalls()

        patient3.die()

        self.assertLocState(clerk, "B", LocationState.isolated)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(patron.dead, [])
        patron.assertCallNumber(1)

        patient2.resurrect()

        self.assertLocState(clerk, "B", LocationState.recovering)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(patron.dead, [])
        patron.assertCallNumber(1)

        patron.next_call()

        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(patron.dead, [patient3])
        patron.assertNoPendingCalls()
        patron.reset()

        patient3.resurrect()
        patient2.be_dying()
        patient3.be_dying()
        patient2.die()
        patient3.die()

        self.assertLocState(clerk, "B", LocationState.isolated)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(patron.dead, [])
        patron.assertCallNumber(1)

        patron.next_call()

        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(patron.dead, [patient2, patient3])
        patron.assertNoPendingCalls()
        patron.reset()

        patient1.be_dying()

        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(patron.dead, [])
        patron.assertNoPendingCalls()

        patient1.die()

        self.assertLocState(clerk, "A", LocationState.isolated)
        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertEqual(clerk.state, MonitorState.isolated)
        self.assertEqual(patron.dead, [])
        patron.assertCallNumber(1)

        patient4.die()

        self.assertLocState(clerk, "A", LocationState.isolated)
        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertLocState(clerk, "C", LocationState.normal)
        self.assertEqual(clerk.state, MonitorState.isolated)
        self.assertEqual(patron.dead, [])
        patron.assertCallNumber(1)

        patient5.die()

        self.assertLocState(clerk, "A", LocationState.isolated)
        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertLocState(clerk, "C", LocationState.isolated)
        self.assertEqual(clerk.state, MonitorState.isolated)
        self.assertEqual(patron.dead, [])
        patron.assertCallNumber(1)

        patient4.resurrect()

        self.assertLocState(clerk, "A", LocationState.isolated)
        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertLocState(clerk, "C", LocationState.recovering)
        self.assertEqual(clerk.state, MonitorState.isolated)
        self.assertEqual(patron.dead, [])
        patron.assertCallNumber(1)

        patient2.resurrect()

        self.assertLocState(clerk, "A", LocationState.isolated)
        self.assertLocState(clerk, "B", LocationState.recovering)
        self.assertLocState(clerk, "C", LocationState.recovering)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(patron.dead, [])
        patron.assertCallNumber(3)

        patient3.resurrect()

        self.assertLocState(clerk, "A", LocationState.isolated)
        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertLocState(clerk, "C", LocationState.recovering)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(patron.dead, [])
        patron.assertCallNumber(2)

        patron.next_call()

        self.assertLocState(clerk, "A", LocationState.isolated)
        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertLocState(clerk, "C", LocationState.normal)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(patron.dead, [patient5])
        patron.assertCallNumber(1)
        patron.reset()

        patient2.be_dying()
        patient3.be_dying()
        patient2.die()
        patient3.die()

        self.assertLocState(clerk, "A", LocationState.isolated)
        self.assertLocState(clerk, "B", LocationState.isolated)
        self.assertLocState(clerk, "C", LocationState.normal)
        self.assertEqual(clerk.state, MonitorState.isolated)
        self.assertEqual(patron.dead, [])
        patron.assertCallNumber(1)

        patron.next_call()

        self.assertLocState(clerk, "A", LocationState.isolated)
        self.assertLocState(clerk, "B", LocationState.isolated)
        self.assertLocState(clerk, "C", LocationState.normal)
        self.assertEqual(clerk.state, MonitorState.recovering)
        self.assertEqual(patron.dead, [])
        patron.assertCallNumber(2)

        patron.next_call()

        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertLocState(clerk, "B", LocationState.isolated)
        self.assertLocState(clerk, "C", LocationState.normal)
        self.assertEqual(clerk.state, MonitorState.recovering)
        self.assertEqual(patron.dead, [patient1])
        patron.assertCallNumber(1)


        patron.next_call()

        self.assertLocState(clerk, "A", LocationState.normal)
        self.assertLocState(clerk, "B", LocationState.normal)
        self.assertLocState(clerk, "C", LocationState.normal)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(patron.dead, [patient1, patient2, patient3])
        patron.assertNoPendingCalls()

    def testWithoutQuarantine(self):
        patron = DummyPatron(self)
        clerk = Clerk(patron, patron, location="A", enable_quarantine=False)
        doctor = IDoctor(clerk)

        patient1 = DummyDoctorPatient(doctor, Recipient("AX"), location="A")
        patient2 = DummyDoctorPatient(doctor, Recipient("BX"), location="B")
        patient3 = DummyDoctorPatient(doctor, Recipient("BY"), location="B")

        self.assertEqual(len(patron.calls), 0)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(len(list(clerk.iter_locations())), 2)
        self.assertEqual(len(patron.dead), 0)
        patron.reset()

        patient2.be_dying()

        self.assertEqual(len(patron.calls), 0)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(len(list(clerk.iter_locations())), 2)
        self.assertEqual(len(patron.dead), 0)
        patron.reset()

        patient3.be_dying()

        self.assertEqual(len(patron.calls), 0)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(len(list(clerk.iter_locations())), 2)
        self.assertEqual(len(patron.dead), 0)
        patron.reset()

        patient2.die()

        self.assertEqual(len(patron.calls), 0)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(len(list(clerk.iter_locations())), 2)
        self.assertEqual(patron.dead, [patient2])
        patron.reset()

        patient2.resurrect()
        patient3.resurrect()

        self.assertEqual(len(patron.calls), 0)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(len(list(clerk.iter_locations())), 2)
        self.assertEqual(patron.dead, [])
        patron.reset()

        patient2.be_dying()
        patient3.be_dying()

        self.assertEqual(len(patron.calls), 0)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(len(list(clerk.iter_locations())), 2)
        self.assertEqual(patron.dead, [])
        patron.reset()

        patient3.die()

        self.assertEqual(len(patron.calls), 0)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(len(list(clerk.iter_locations())), 2)
        self.assertEqual(patron.dead, [patient3])
        patron.reset()

        doctor.on_patient_removed(patient3)
        patient2.die()

        self.assertEqual(len(patron.calls), 0)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(len(list(clerk.iter_locations())), 2)
        self.assertEqual(patron.dead, [patient2])
        patron.reset()

        doctor.on_patient_removed(patient2)
        patient1.be_dying()

        self.assertEqual(len(patron.calls), 0)
        self.assertEqual(clerk.state, MonitorState.normal)
        self.assertEqual(len(list(clerk.iter_locations())), 1)
        self.assertEqual(patron.dead, [])
        patron.reset()


class TestLocation(common.TestCase):

    def testPauseResume(self):
        clerk = DummyClerk()
        loc = Location(clerk, "localhost")
        patient1 = DummyLocationPatient(loc, Recipient("XXX"))
        patient2 = DummyLocationPatient(loc, Recipient("YYY"), period=42)

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 2)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 0)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        loc._pause()
        patient1.be_dying()
        patient2.be_dying()
        patient1.die()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 1)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        loc._resume()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 1)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        patient2.die()

        self.assertEqual(loc.state, LocationState.isolated)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 2)
        self.assertEqual(clerk.quarantined, [loc])
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        loc._pause()

        self.assertEqual(loc.state, LocationState.isolated)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 2)
        self.assertEqual(clerk.quarantined, [loc])
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        loc._resume()

        # Ask again for quarantine
        self.assertEqual(loc.state, LocationState.isolated)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 2)
        self.assertEqual(clerk.quarantined, [loc, loc])
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset_all()

        loc._pause()

        patient1.resurrect()

        self.assertEqual(loc.state, LocationState.recovering)

        patient2.resurrect()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)

        loc._resume()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 2)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 0)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        loc._pause()
        patient1.die()

        self.assertEqual(loc.state, LocationState.normal)

        patient2.die()

        self.assertEqual(loc.state, LocationState.isolated)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)

        loc._resume()

        self.assertEqual(loc.state, LocationState.isolated)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 2)
        self.assertEqual(clerk.quarantined, [loc])
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset_all()

        loc._start_quarantine()

        patient2.resurrect()

        self.assertEqual(loc.state, LocationState.recovering)
        self.assertEqual(loc.count_alive(), 1)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(clerk.quarantined, [])
        self.assertEqual(clerk.recovering, [loc])
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset_all()

        self.assertEqual(loc._start_recovery(), 3)

        loc._pause()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 1)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(clerk.quarantined, [])
        self.assertEqual(clerk.recovering, [])
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset_all()

        patient1.resurrect()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 2)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 0)
        self.assertEqual(clerk.quarantined, [])
        self.assertEqual(clerk.recovering, [])
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset_all()

        loc._resume()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 2)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 0)
        self.assertEqual(clerk.quarantined, [])
        self.assertEqual(clerk.recovering, [])
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset_all()

        patient1.be_dying()
        patient2.be_dying()
        patient1.die()
        patient2.die()

        self.assertEqual(loc.state, LocationState.isolated)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 2)
        self.assertEqual(clerk.quarantined, [loc])
        self.assertEqual(clerk.recovering, [])
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset_all()

        loc._start_quarantine()
        patient1.resurrect()

        self.assertEqual(loc.state, LocationState.recovering)
        self.assertEqual(loc.count_alive(), 1)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(clerk.quarantined, [])
        self.assertEqual(clerk.recovering, [loc])
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset_all()

        loc._pause()

        patient1.die()

        self.assertEqual(loc.state, LocationState.isolated)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 2)
        self.assertEqual(clerk.quarantined, [])
        self.assertEqual(clerk.recovering, [])
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset_all()

        loc._resume()

        self.assertEqual(loc.state, LocationState.isolated)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 2)
        self.assertEqual(clerk.quarantined, [loc])
        self.assertEqual(clerk.recovering, [])
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset_all()

        loc._pause()
        patient1.resurrect()

        self.assertEqual(loc.state, LocationState.recovering)
        self.assertEqual(loc.count_alive(), 1)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(clerk.quarantined, [])
        self.assertEqual(clerk.recovering, [])
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset_all()

        loc._resume()

        self.assertEqual(loc.state, LocationState.recovering)
        self.assertEqual(loc.count_alive(), 1)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(clerk.quarantined, [])
        self.assertEqual(clerk.recovering, [loc])
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset_all()

    def testMultiplePatient(self):
        clerk = DummyClerk()
        loc = Location(clerk, "localhost")
        patient1 = DummyLocationPatient(loc, Recipient("XXX"))
        patient2 = DummyLocationPatient(loc, Recipient("YYY"), period=42)

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 2)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 0)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        patient1.be_dying()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 1)
        self.assertEqual(loc.count_dying(), 1)
        self.assertEqual(loc.count_dead(), 0)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        patient1.die()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 1)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(clerk.dead, [patient1])
        clerk.reset()

        patient1.resurrect()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 2)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 0)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        patient1.be_dying()
        patient2.be_dying()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 2)
        self.assertEqual(loc.count_dead(), 0)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        patient1.die()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 1)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)

        patient2.resurrect()

        self.assertEqual(loc.state, LocationState.recovering)
        self.assertEqual(loc.count_alive(), 1)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(clerk.recovering, [loc])
        self.assertEqual(clerk.dead, [])
        clerk.reset_all()

        loc._start_recovery()
        loc._quarantine_lifted()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 1)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(clerk.dead, [patient1])
        clerk.reset()

        patient1.resurrect()
        patient1.be_dying()
        patient2.be_dying()
        patient2.die()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 1)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        patient1.die()

        self.assertEqual(loc.state, LocationState.isolated)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 2)
        self.assertEqual(clerk.quarantined, [loc])
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        loc._start_quarantine()

        self.assertEqual(loc.state, LocationState.isolated)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 2)
        self.assertEqual(clerk.quarantined, [loc])
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        patient1.resurrect()

        self.assertEqual(loc.state, LocationState.recovering)
        self.assertEqual(loc.count_alive(), 1)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(clerk.recovering, [loc])
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        self.assertEqual(loc._start_recovery(), 42)

        patient2.resurrect()

        self.assertEqual(loc.state, LocationState.normal) # got recovered
        self.assertEqual(loc.count_alive(), 2)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 0)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(clerk.recovering, [loc])
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset_all()

        loc._quarantine_lifted()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 2)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 0)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        patient1.resurrect()
        patient1.be_dying()
        patient2.be_dying()
        patient1.die()
        patient2.die()

        self.assertEqual(loc.state, LocationState.isolated)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 2)
        self.assertEqual(clerk.quarantined, [loc])
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset_all()

        loc._start_quarantine()
        loc._start_recovery()
        loc._quarantine_lifted()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 2)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(clerk.dead, [patient1, patient2])
        clerk.reset()

        patient1.resurrect()
        patient2.resurrect()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 2)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 0)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(clerk.recovering, [loc])
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset_all()

        loc._start_quarantine()

        self.assertEqual(loc.state, LocationState.isolated)
        self.assertEqual(loc.count_alive(), 2)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 0)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        patient1.be_dying()
        patient2.be_dying()
        patient1.die()
        patient2.die()

        self.assertEqual(loc.state, LocationState.isolated)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 2)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        patient1.resurrect()

        self.assertEqual(loc.state, LocationState.recovering)
        self.assertEqual(loc.count_alive(), 1)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(clerk.recovering, [loc])
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset_all()

        self.assertEqual(loc._start_recovery(), 42)
        loc._quarantine_lifted()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 1)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(clerk.dead, [patient2])
        clerk.reset()

        patient2.resurrect()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 2)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 0)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(clerk.dead, [])
        clerk.reset()

        patient2.be_dying()
        patient1.die()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 1)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(clerk.dead, [])
        clerk.reset()

        loc._remove_patient(patient2)

        self.assertEqual(loc.state, LocationState.isolated)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(clerk.quarantined, [loc])
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(clerk.dead, [])
        clerk.reset()

    def testSinglePatient(self):
        clerk = DummyClerk()
        loc = Location(clerk, "localhost")
        patient = DummyLocationPatient(loc, Recipient("XXX"))

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 1)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 0)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        patient.be_dying()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 1)
        self.assertEqual(loc.count_dead(), 0)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        patient.die()

        self.assertEqual(loc.state, LocationState.isolated)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(clerk.quarantined, [loc])
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        loc._start_quarantine()

        self.assertEqual(loc.state, LocationState.isolated)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(clerk.quarantined, [loc])
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset_all()

        patient.resurrect()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 1)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 0)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(clerk.recovering, [])
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        self.assertEqual(loc._start_recovery(), 0)

        self.assertEqual(loc.state, LocationState.normal) # no recovery needed
        self.assertEqual(loc.count_alive(), 1)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 0)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(clerk.recovering, [])
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset_all()

        loc._quarantine_lifted()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 1)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 0)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        patient.die()

        self.assertEqual(loc.state, LocationState.isolated)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(clerk.quarantined, [loc])
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset_all()

        loc._start_quarantine()
        loc._start_recovery()
        loc._quarantine_lifted()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(clerk.dead, [patient])
        clerk.reset()

        patient.resurrect()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 1)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 0)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        loc._start_quarantine()

        self.assertEqual(loc.state, LocationState.isolated)
        self.assertEqual(loc.count_alive(), 1)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 0)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        patient.be_dying()

        self.assertEqual(loc.state, LocationState.isolated)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 1)
        self.assertEqual(loc.count_dead(), 0)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        patient.die()

        self.assertEqual(loc.state, LocationState.isolated)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        self.assertEqual(loc._start_recovery(), 3)

        self.assertEqual(loc.state, LocationState.recovering)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        loc._quarantine_lifted()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(clerk.dead, [patient])
        clerk.reset()

        loc._start_quarantine()

        self.assertEqual(loc.state, LocationState.isolated)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()

        loc._quarantine_lifted()

        self.assertEqual(loc.state, LocationState.normal)
        self.assertEqual(loc.count_alive(), 0)
        self.assertEqual(loc.count_dying(), 0)
        self.assertEqual(loc.count_dead(), 1)
        self.assertEqual(len(clerk.quarantined), 0)
        self.assertEqual(len(clerk.recovering), 0)
        self.assertEqual(len(clerk.dead), 0)
        clerk.reset()
