import signal
import os

from twisted.internet import reactor
from zope.interface import implements

from feat.agencies import agency
from feat.agencies.net import agency as net_agency
from feat.agencies.net.broker import BrokerRole
from feat.agents.base import partners, resource
from feat.common import adapter, log
from feat.gateway import models


@adapter.register(net_agency.Agency, models.IRoot)
class Root(object):

    implements(models.IRoot)

    def __init__(self, agency):
        self._agency = agency

    def __getattr__(self, attr):
        return getattr(self._agency, attr)

    def is_master(self):
        return self._agency.role is BrokerRole.master

    def full_shutdown(self):
        return self._agency.full_shutdown(stop_process=True)


@adapter.register(net_agency.Agency, models.IAgency)
class Agency(object):

    implements(models.IAgency)

    def __init__(self, agency):
        self._agency = agency

    def __getattr__(self, attr):
        return getattr(self._agency, attr)

    @property
    def default_gateway_port(self):
        return net_agency.DEFAULT_GW_PORT

    def shutdown_agency(self):
        return self._agency.shutdown(stop_process=True)

    def terminate_agency(self):
        os.kill(os.getpid(), signal.SIGTERM)

    def kill_agency(self):
        os.kill(os.getpid(), signal.SIGKILL)


@adapter.register(agency.AgencyAgent, models.IAgent)
class Agent(object):

    implements(models.IAgent)

    def __init__(self, medium):
        self._medium = medium
        self._agent = medium.get_agent()

    ### models.IAgent ###

    @property
    def agent_id(self):
        return self._agent.get_agent_id()

    @property
    def instance_id(self):
        return self._agent.get_instance_id()

    @property
    def agent_type(self):
        return self._agent.descriptor_type

    @property
    def agent_status(self):
        return self._agent.get_status()

    @property
    def agency_id(self):
        return self._medium.agency.agency_id

    def have_resources(self):
        return isinstance(self._agent, resource.AgentMixin)

    def iter_attributes(self):
        return iter([])

    def iter_partners(self):
        return iter(self._agent.query_partners("all"))

    def iter_resources(self):
        return self._agent.get_resource_usage().iteritems()

    def terminate_agent(self):
        agent_id = self._medium.get_agent_id()
        d = self._medium.agency.wait_event(agent_id, "unregistered")
        self._medium.terminate()
        return d

    def kill_agent(self):
        return self._medium.terminate_hard()


@adapter.register(agency.AgencyAgent, models.IMonitor)
class Monitor(Agent):

    implements(models.IMonitor)

    def __init__(self, medium):
        Agent.__init__(self, medium)

    ### models.IMonitor ###

    def get_monitoring_status(self):
        return self._agent.get_monitoring_status()


@adapter.register(partners.BasePartner, models.IPartner)
class Partner(object):

    def __init__(self, partner):
        self._partner = partner

    @property
    def partner_type(self):
        return self._partner.type_name

    @property
    def agent_id(self):
        return self._partner.recipient.key

    @property
    def shard_id(self):
        return self._partner.recipient.shard

    @property
    def role(self):
        return self._partner.role
