from zope.interface import Interface, Attribute


class IModel(Interface):
    pass


class IRoot(IModel):

    def is_master():
        """Returns if the agency is a master."""

    def locate_master():
        """Returns a tuple with host, port
        and if redirection is needed or None"""

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

    def spawn_agent(desc, *args, **kwargs):
        """Spawn an agent on this agency."""

    def full_shutdown():
        """Shut all agencies down."""


class IAgency(IModel):

    agency_id = Attribute("Agency's identifier")
    role = Attribute("Agency role as a broker.")
    default_gateway_port = Attribute("")

    def get_hostname():
        """Returns agency's hostname."""

    def shutdown_agency():
        """Shut the agency down."""

    def kill_agency():
        """Kill the agency."""

    def get_logging_filter():
        """Returns the global logging filter currently in use."""

    def set_logging_filter(filter):
        """Sets the global logging filter."""


class IAgent(IModel):

    agency_id = Attribute("Agent's identifier")
    instance_id = Attribute("Agent's instance number")
    agent_type = Attribute("")
    agent_status = Attribute("")
    agency_id = Attribute("")

    def has_resources():
        """Returns if the agent have resources."""

    def iter_attributes():
        """Iterates over agent's attributes."""

    def iter_partners():
        """Iterates over agent's partners."""

    def iter_resources():
        """Iterates over agent's resources."""

    def terminate_agent():
        """Terminate the agent."""

    def kill_agent():
        """Kill the agent."""


class IPartner(IModel):

    partner_type = Attribute("Partner's type")
    agent_id = Attribute("Partner's agent identifier")
    shard_id = Attribute("Partner's shard identifier")
    role = Attribute("Partner's role")


class IMonitor(IAgent):

    def get_monitoring_status(self):
        """Returns monitor status."""
