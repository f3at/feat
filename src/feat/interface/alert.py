from zope.interface import Interface, Attribute
from feat.common import enum


class Severity(enum.Enum):

    warn, critical = range(2)


class IAlertFactory(Interface):

    name = Attribute('C{str} unique name of the service')
    severity = Attribute('L{Severity}')

    def __call__(hostname, agent_id, status_info):
        '''Construct IAlert'''


class IAlert(Interface):

    name = Attribute('C{str} unique name of the service')
    hostname = Attribute('Host name running the agent who raised the alert')
    status_info = Attribute('C{str} optional string specifing more details.')
    agent_id = Attribute("C{str} agent_id who raised the alert")
    severity = Attribute('L{Severity}')
