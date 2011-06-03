from zope.interface import implements

from feat.agencies import agency
from feat.agencies.net import agency as net_agency
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

    def iter_attributes():
        return iter([])

    def iter_partners():
        return iter([])

    def iter_resources():
        return iter([])
