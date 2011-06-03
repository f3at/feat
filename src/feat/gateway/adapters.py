from zope.interface import implements

from feat.agencies import agency
from feat.agencies.net import agency as net_agency
from feat.agents.base import partners
from feat.common import adapter
from feat.gateway import models


@adapter.register(net_agency.Agency, models.IRoot)
class Root(object):

    implements(models.IRoot)

    def __init__(self, agency):
        self._agency = agency

    def __getattr__(self, attr):
        return getattr(self._agency, attr)


@adapter.register(net_agency.Agency, models.IAgency)
class Agency(object):

    implements(models.IAgency)

    def __init__(self, agency):
        self._agency = agency

    def __getattr__(self, attr):
        return getattr(self._agency, attr)


@adapter.register(agency.AgencyAgent, models.IAgent)
class Agent(object):

    implements(models.IAgency)

    def __init__(self, medium):
        self._medium = medium
        self._agent = medium.get_agent()

    ### models.IAgencyModel ###

    @property
    def agent_id(self):
        return self._agent.get_agent_id()

    @property
    def instance_id(self):
        return self._agent.get_instance_id()

    @property
    def agent_type(self):
        return self._agent.descriptor_type

    def iter_attributes(self):
        return iter([])

    def iter_partners(self):
        return iter(self._agent.query_partners("all"))

    def iter_resources(self):
        return iter([])


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
