from zope.interface import Interface, Attribute

from feat.common import enum

__all__ = ["InterestType", "IInitiatorFactory", "IAgencyInterest",
           "IInterest", "IInitiator", "IInterested", "InitiatorFailed",
           "InitiatorExpired"]


class InterestType(enum.Enum):
    '''Type of Interest:

    - private:   Dialog is initiated with 1-1 communication
    - public:     Dialog is initiated with 1-* communication
    '''

    (private, public) = range(2)


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


class IInitiator(Interface):
    '''Represent the side of a protocol initiating the dialog.'''

    def initiate(*args, **kwargs):
        '''Initiate initiator. Should be call before anything else.'''

    def wait_for_state(*states):
        '''Returns a Deferred that will be fired when the initiator
        state changed to one of the specified state.'''

    def wait_finish():
        '''Returns a Deferred that will be fired
        when the initiator finishes.'''

    def get_expiration_time():
        '''
        Returns number of seconds since epoch when the expiration call for
        current state will fire.
        '''


class InitiatorFailed(Exception):
    '''
    The intiating side of the dialog did not finish with successful status
    '''


class InitiatorExpired(InitiatorFailed):
    '''
    A protocol peer has been terminated by the expiration call.
    '''


class IInterested(Interface):
    '''Represent the side of a protocol interested in a dialog.'''

    protocol_id = Attribute("Protocol id")

    def initiate(*args, **kwargs):
        '''Initiate the interested protocol.'''

    def get_expiration_time():
        '''
        Returns number of seconds since epoch when the expiration call for
        current state will fire.
        '''
