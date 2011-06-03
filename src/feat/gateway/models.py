from zope.interface import Interface, Attribute


class IModel(Interface):
    pass


class IRoot(IModel):

    def iter_agents():
        """Iterates over the known agents."""

    def iter_agencies():
        """Iterate over all agencies."""

    def get_agency(agency_id):
        """Returns an agency or None."""

    def locate_agency(agency_id):
        """Locate an agency form its identifier.
        Returns a deferred fired with a tuple of host name,
        port and if redirect is needed, or None if not located."""

    def get_agent(agent_id):
        """Returns an agent medium or None."""

    def locate_agent(agent_id):
        """Locate an agent form its identifier.
        Returns a deferred fired with a tuple of host name,
        port and if redirect is needed, or None if not located."""


class IAgency(IModel):

    agency_id = Attribute("Agency's identifier")
    role = Attribute("Agency role as a broker.BrokerRole")


class IAgent(IModel):

    agency_id = Attribute("Agent's identifier")
    instance_id = Attribute("Agent's instance number")
    agent_type = Attribute("")

    def iter_attributes():
        """Iterates over agent's attributes."""

    def iter_partners():
        """Iterates over agent's partners."""

    def iter_resources():
        """Iterates over agent's resources."""
