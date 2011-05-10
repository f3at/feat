from zope.interface import Interface, Attribute

from feat.common import enum

__all__ = ['DEFAULT_HEARTBEAT_PERIOD',
           'DEFAULT_MAX_SKIPPED_HEARTBEAT',
           'DEFAULT_CHECK_PERIOD',
           'IDoctor', 'IPatient', 'PatientState',
           'IHeartMonitorFactory', 'IHeartMonitor',
           'IPacemakerFactory', 'IPacemaker']

DEFAULT_HEARTBEAT_PERIOD = 12
DEFAULT_MAX_SKIPPED_HEARTBEAT = 2
DEFAULT_CHECK_PERIOD = DEFAULT_HEARTBEAT_PERIOD / 3.0


class PatientState(enum.Enum):

    alive, dying, dead = range(3)


class IPatient(Interface):

        agent_id = Attribute("Monitored agent identifier")
        instance_id = Attribute("Monitored agent instance identifier")
        payload = Attribute("Custom payload")
        period = Attribute("Monitoring period")
        max_skip = Attribute("Maximum hearbeat skip allowed")
        last_beat = Attribute("Last heartbeat time")
        state = Attribute("Current state")


class IDoctor(Interface):

    def register_interest(factory, *args, **kwargs):
        """Register a protocol interest."""

    def get_time():
        """Returns the current time."""

    def call_later(fun, *args, **kwargs):
        """Schedule a function call after a specified amount of time."""

    def cancel_delayed_call(callid):
        """Cancel a delayed call created by call_later()."""

    def on_heart_failed(agent_id, instance_id, payload):
        """Called when an agent's heart stop beating."""


class IHeartMonitorFactory(Interface):

    def __call__(agent):
        """Creates an Instance supporting IHeartMonitor."""


class IHeartMonitor(Interface):

    def startup():
        """Initializes the heart beat collector."""

    def cleanup():
        """Cleanup the hear beat monitor."""

    def pause(self):
        """Stops checking on patients."""

    def resume(self):
        """Resumes checking on patients."""

    def add_patient(agent_id, instance_id, payload=None,
                    period=None, max_skip=None):
        """Starts monitoring specified agent instance.
        If the patient dies it will be removed, no needs
        to call remove_patien()."""

    def remove_patient(agent_id, instance_id):
        """Stops monitoring specified agent instance."""

    def check_patients():
        """Checks all patients."""

    def iter_patients():
        """Iterate over all patient, as IPatient.
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
