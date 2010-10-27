from zope.interface import Interface


class IAgency(Interface):
    '''The agency. It manages agents communications, state, log, journal...
    It only publishes the interface global for all agents, agent normally use
    there L{IAgencyAgent} reference given at initialization time.'''

    def start_agent(factory, descriptor, *args, **kwargs):
        '''Start new agent from factory. Returns the L{IAgencyAngent}'''
