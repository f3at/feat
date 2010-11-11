from zope.interface import Interface

__all__ = ["IAgency"]


class IAgency(Interface):
    '''The agency. It manages agents communications, state, log, journal...
    It only publishes the interface global for all agents, agent normally use
    there L{IAgencyAgent} reference given at initialization time.'''

    def start_agent(factory, descriptor, *args, **kwargs):
        '''Start new agent from factory. Returns the L{IAgencyAngent}'''

    def callLater(timeout, method, *args, **kwargs):
        '''
        Wrapper for reactor.callLater.
        '''

    def get_time():
        '''
        Use this to get current time. Should fetch the time from NTP server
        @returns: Number of seconds since epoch
        '''
