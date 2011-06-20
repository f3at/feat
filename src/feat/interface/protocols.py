from zope.interface import Interface, Attribute

from feat.common import enum

__all__ = ["ProtocolFailed", "ProtocolNotCriticalError",
           "ProtocolExpired", "ProtocolCancelled",
           "InterestType", "IInitiatorFactory", "IAgencyInterest",
           "IInterest", "IAgentProtocol", "IInitiator", "IInterested",
           "IAgencyProtocol"]


class InterestType(enum.Enum):
    '''Type of Interest:

    - private:   Dialog is initiated with 1-1 communication
    - public:     Dialog is initiated with 1-* communication
    '''

    (private, public) = range(2)


class ProtocolFailed(Exception):
    '''The protocol failed.'''


class ProtocolNotCriticalError(ProtocolFailed):
    '''Not critical error that should not be logged as error.'''


class ProtocolExpired(ProtocolNotCriticalError):
    '''A protocol peer has been terminated by the expiration call.'''


class ProtocolCancelled(ProtocolNotCriticalError):
    '''
    A protocol has been canceled.
    '''


class IInitiatorFactory(Interface):
    '''This class represent a protocol initiator.
    It defines a protocol type, a protocol identifier and can be
    called to create an instance assuming the initiator role of the protocol.
    '''

    protocol_type = Attribute("Protocol type")
    protocol_id = Attribute("Protocol id")

    def __call__(agent, medium, *args, **kwargs):
        '''Creates an instance implementing L{IInitiator}
        assuming the initiator role.'''


class IAgencyInterest(Interface):
    '''Agency side interest.'''

    def bind_to_lobby():
        pass

    def unbind_from_lobby():
        pass


class IAgencyProtocol(Interface):
    '''Base interface for all agency-side protocol mediumns.'''

    def is_idle(self):
        '''Returns if the protocol is idle.'''

    def terminate(result=None):
        '''Called to terminate the protocol with the given result.'''

    def fail(failure):
        '''Called by agent-side when a protocol has failed or canceled.'''


class IInterest(Interface):
    '''This class represent an interest in a type of protocol.
    It defines a protocol type, a protocol identifier and can be called
    to create an instance assuming the interested role of the protocol.
    '''

    protocol_type = Attribute("Protocol type")
    protocol_id = Attribute("Protocol id")
    initiator = Attribute("A message class that initiates the dialog. "
                          "Should implement L{IFirstMessage}")
    concurrency = Attribute("Number of concurrent instances allowed.")
    interest_type = Attribute("Type of interest L{InterestType}")

    def __call__(agent, medium, *args, **kwargs):
        '''Creates an instance assuming the interested role.'''


class IAgentProtocol(Interface):

    def initiate(*args, **kwargs):
        '''Initiate protocol.'''

    def cancel():
        '''Called by agent-side or agency-side to cancel the protocol.'''


class IInitiator(IAgentProtocol):
    '''Represent the side of a protocol initiating the dialog.'''

    def wait_for_state(*states):
        '''Returns a Deferred that will be fired when the initiator
        state changed to one of the specified state.'''

    def wait_finish():
        '''Returns a Deferred that will be fired
        when the initiator finishes.'''


class IInterested(IAgentProtocol):
    '''Represent the side of a protocol interested in a dialog.'''

    protocol_id = Attribute("Protocol id")
