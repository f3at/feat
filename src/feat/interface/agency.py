from zope.interface import Interface
from feat.common import enum


__all__ = ["ExecMode", "IAgency"]


class ExecMode(enum.Enum):
    '''
    Used for registering the dependencies.
    '''

    production, test, simulation = range(3)


class IAgency(Interface):
    '''The agency. It manages agents communications, state, log, journal...
    It only publishes the interface global for all agents, agent normally use
    there L{IAgencyAgent} reference given at initialization time.'''

    def start_agent(descriptor, *args, **kwargs):
        '''
        Start new agent for the given descriptor.
        The factory is lookuped at in the agents registry.
        The args and kwargs will be passed to the agents initiate() method.
        @return_type: L{IAgencyAngent}
        '''

    def get_time():
        '''
        Use this to get current time. Should fetch the time from NTP server
        @returns: Number of seconds since epoch
        '''

    def set_mode(component, mode):
        '''
        Tell in which mode should the given componenet operate.
        @param component: String representing the component.
        @param mode: L{ExecMode}
        '''

    def get_mode(component):
        '''
        Get the mode to run given component.
        '''
