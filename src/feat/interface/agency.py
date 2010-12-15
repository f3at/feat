from zope.interface import Interface

__all__ = ["IAgency"]


class IAgency(Interface):
    '''The agency. It manages agents communications, state, log, journal...
    It only publishes the interface global for all agents, agent normally use
    there L{IAgencyAgent} reference given at initialization time.'''

    def start_agent(descriptor, *args, **kwargs):
        '''
        Start new agent for the given descriptor.
        The factory is lookuped at in the agents registry.
        @return_type: L{IAgencyAngent}
        '''

    def get_time():
        '''
        Use this to get current time. Should fetch the time from NTP server
        @returns: Number of seconds since epoch
        '''
