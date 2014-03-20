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
from zope.interface import Interface, Attribute

from feat.common import enum, error

__all__ = ['DEFAULT_HEARTBEAT_PERIOD',
           'DEFAULT_DEATH_SKIPS', 'DEFAULT_DYING_SKIPS',
           'DEFAULT_CONTROL_PERIOD', 'DEFAULT_NOTIFICATION_PERIOD',
           'DEFAULT_HOST_QUARANTINE_LENGTH', 'DEFAULT_SELF_QUARANTINE_LENGTH',
           'RestartFailed', 'MonitoringFailed',
           'PatientState', 'LocationState', 'MonitorState', 'RestartStrategy',
           'ILocationStatus',
           'IClerkFactory', 'IClerk', 'ICoroner', 'IAssistant',
           'IDoctor', 'IPatientStatus',
           'IIntensiveCareFactory', 'IIntensiveCare',
           'IPacemakerFactory', 'IPacemaker']

DEFAULT_HEARTBEAT_PERIOD = 12
DEFAULT_DEATH_SKIPS = 3
DEFAULT_DYING_SKIPS = 1.5
DEFAULT_CONTROL_PERIOD = DEFAULT_HEARTBEAT_PERIOD / 3.0
DEFAULT_NOTIFICATION_PERIOD = 10

DEFAULT_HOST_QUARANTINE_LENGTH = 60*2
DEFAULT_SELF_QUARANTINE_LENGTH = 60*3


class RestartFailed(error.FeatError):
    pass


class MonitoringFailed(error.NonCritical):
    log_level = 3
    log_line_template = ("Monitor agent not found. This is normal "
                         "I will keep on retrying until he is started.")


class PatientState(enum.Enum):

    alive, dying, dead = range(3)


class LocationState(enum.Enum):
    """
    Enum for the monitoring state:

     - normal       - Stable state. Normal location behaviours.
     - isolated     - Temporary state. All patient are dead so wait extra time
                      to to let a chance to recover temporary network failures.
     - recovering   - Temporary state. After being isolated some patient
                      resurrected. Give the other some extra time to ressurect
                      before handling there death.
    """

    normal, isolated, recovering = range(3)


class MonitorState(enum.Enum):
    """
    Enum for the monitoring state:

     - normal       - Stable state. Normal monitoring behaviours.
     - isolated     - Temporary state. All locations minus the one of the
                      monitor itself are isolated, so the monitoring is
                      waiting extra time to cover for a temporary network
                      disconnection.
     - recovering   - Temporary state. After waiting extra time isolated
                      nothing changed so we are now in recovering state
                      meaning that each locations are given there usual
                      isolation time to recover or will be handled with.
     - disconnected - Stable state. the monitor is disconnected from the
                      network.  Nothing should be done until reconnected.
    """

    normal, isolated, recovering, disconnected = range(4)


class RestartStrategy(enum.Enum):
    """
    Enum for the IAgentFactory.restart_strategy attribute
     - buryme    - Don't try to restart agent, just notify everybody about the
                   death.
     - local     - May be be restarted but only in the same shard.
     - wherever  - May be restarted wherever in the cluster.
     - monitor   - Special strategy used by monitoring agents. When monitor
                   cannot be restarted in the shard before dying for good his
                   partners will get monitored by the monitoring agent who is
                   resolving this issue.
    """
    buryme, local, wherever, monitor = range(4)


class ILocationStatus(Interface):

    name = Attribute("Location name.")
    state = Attribute("locartion state as a LocationState")

    def has_patient(identifier):
        """Returns if the location has specified patient.
        @param identifier: A recipient or and agent identifier.
        @type  identifier: IRecipient or str
        @rtype: bool"""

    def get_patient(identifier):
        """Returns a patient status or None.
        @param identifier: A recipient or and agent identifier.
        @type  identifier: IRecipient or str
        @rtype: IPatientStatus"""

    def iter_patients():
        """Iterates over patient status on this location.
        @rtype: IPatientStatus"""


class IPatientStatus(Interface):

    patient_type = Attribute("Patient type name.")
    recipient = Attribute("Monitored agent identifier")
    location = Attribute("Location of the patient")
    last_beat = Attribute("Last heartbeat time")
    state = Attribute("Current state")

    period = Attribute("Expected heart beats period.")
    death_skips = Attribute("Skipped heart beat for death.")
    dying_skips = Attribute("Skipped heart beat for dying.")


class IClerkFactory(Interface):

    def __call__(assistant, coroner,
                 self_location="localhost", enable_quarantine=True,
                 host_quarantine_length=DEFAULT_HOST_QUARANTINE_LENGTH,
                 self_quarantine_length=DEFAULT_SELF_QUARANTINE_LENGTH):
        """Creates a new clerk."""


class IClerk(Interface):

    state = Attribute("State of the monitoring location as a LocationState.")
    location = Attribute("Name of the clerk location.")

    def startup():
        """Initializes the clerk with specified heart monitor and coroner."""

    def cleanup():
        """Cleanup the clerk."""

    def on_disconnected():
        """Called when network connectivity was lost."""

    def on_reconnected():
        """Called when network connectivity was restored."""

    def has_patient(identifier):
        """Returns if the clerk knows about the specified patient.
        @param identifier: A recipient or and agent identifier.
        @type  identifier: IRecipient or str
        @rtype: bool"""

    def get_patient(identifier):
        """Gets patient status.
        @param identifier: A recipient or and agent identifier.
        @type  identifier: IRecipient or str
        @rtype: IPatientStatus"""

    def get_location(location):
        """Gets location status.
        @rtype: ILocationStatus"""

    def iter_locations():
        """Iterate over location status as ILocationStatus."""


class ICoroner(Interface):

    def on_patient_dead(patient):
        """Called when an agent's definitely dead."""


class IAssistant(Interface):

    def initiate_protocol(factory, *args, **kwargs):
        """Initiates a protocol."""

    def register_interest(factory, *args, **kwargs):
        """Register a protocol interest."""

    def get_time():
        """Returns the current time."""

    def call_later(fun, *args, **kwargs):
        """Schedule a function call after a specified amount of time."""

    def cancel_delayed_call(callid):
        """Cancel a delayed call created by call_later()."""


class IDoctor(Interface):

    def on_patient_added(patient):
        """Called when a new patient was added."""

    def on_patient_dying(patient):
        """Called when a patient is dying."""

    def on_patient_died(patient):
        """Called when a patient just died."""

    def on_patient_resurrected(patient):
        """Called when a patient came back to life."""

    def on_patient_removed(patient):
        """Called when a new patient was removed."""


class IIntensiveCareFactory(Interface):

    def __call__(assistant, doctor, control_period=None):
        """Creates an Instance supporting IHeartMonitor."""


class IIntensiveCare(Interface):

    def startup():
        """Initializes the heart beat collector with specified doctor."""

    def cleanup():
        """Cleanup the hear beat monitor."""

    def pause(self):
        """Stops checking on patients."""

    def resume(self):
        """Resumes checking on patients."""

    def has_patient(identifier):
        """returns if the monitor knows about a patient.
        @param identifier: A recipient or and agent identifier.
        @type  identifier: IRecipient or str"""

    def add_patient(recipient, location,
                    period=None, dying_skips=None, death_skips=None):
        """Starts monitoring specified agent instance."""

    def remove_patient(identifier):
        """Stops monitoring patient with specified identifier.
        @param identifier: A recipient or and agent identifier.
        @type  identifier: IRecipient or str"""

    def control_patients():
        """Control the status of all patients."""

    def get_patient(identifier):
        """Returns patient status.
        @param identifier: A recipient or and agent identifier.
        @type  identifier: IRecipient or str
        @rtype: IPatietnStatus"""

    def iter_patients():
        """Iterate over all patient status, as IPatientStatus.
        Not a side-effect, Should be called
        from OUTSIDE of the hamster ball."""


class IPacemakerFactory(Interface):

    def __call__(agent, monitor, period=None):
        pass


class IPacemaker(Interface):

    def startup():
        pass

    def cleanup():
        pass
