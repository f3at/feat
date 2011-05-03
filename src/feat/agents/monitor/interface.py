from zope.interface import Interface

from feat.common import enum

__all__ = ['DEFAULT_HEARTBEAT_PERIOD',
           'DEFAULT_MAX_SKIPPED_HEARTBEAT',
           'DEFAULT_CHECK_PERIOD',
           'IDoctor', 'PatientState',
           'IHeartMonitorFactory', 'IHeartMonitor',
           'IPacemakerFactory', 'IPacemaker']

DEFAULT_HEARTBEAT_PERIOD = 12
DEFAULT_MAX_SKIPPED_HEARTBEAT = 2
DEFAULT_CHECK_PERIOD = 1


class PatientState(enum.Enum):

    alive, dying, dead = range(3)


class IDoctor(Interface):

    def register_interest(factory, *args, **kwargs):
        """Register a protocol interest."""

    def get_time():
        """Returns the current time."""

    def call_later(fun, *args, **kwargs):
        """Schedule a function call after a specified amount of time."""

    def cancel_delayed_call(callid):
        """Cancel a delayed call created by call_later()."""

    def on_heart_failed(agent_id, instance_id):
        """Called when an agent's heart stop beating."""


class IHeartMonitorFactory(Interface):

    def __call__(agent):
        """Creates an Instance supporting IHeartMonitor."""


class IHeartMonitor(Interface):

    def initiate():
        """Initializes the heart beat collector."""

    def cleanup():
        """Cleanup the hear beat monitor."""

    def add_patient(agent_id, instance_id, period=None):
        """Starts monitoring specified agent instance.
        If the patient dies it will be removed, no needs
        to call remove_patien()."""

    def remove_patient(agent_id, instance_id):
        """Stops monitoring specified agent instance."""

    def check_patients():
        """Checks all patients."""


class IPacemakerFactory(Interface):

    def __call__(agent, monitor, period=None):
        pass


class IPacemaker(Interface):

    def stop():
        pass
