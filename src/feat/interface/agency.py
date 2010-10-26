from zope.interface import Interface


class IAgency(Interface):
    '''The adgency. It manage agents communications, state, log, journal...
    This only publish the interface global for all agents, agent normally use
    there L{IAgencyAgent} reference given at initialization time.'''

    def start_agent(factory, descriptor, *args, **kwargs):
        pass