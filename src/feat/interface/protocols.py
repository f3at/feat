from zope.interface import Interface, Attribute

from feat.common import enum

__all__ = ["InterestType", "IInitiatorFactory",
           "IInterest", "IInitiator", "IInterested"]


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


class IInterest(Interface):
    '''This class represent an interest in a type of protocol.
    It defines a protocol type, a protocol identifier and can be called
    to create an instance assuming the interested role of the protocol.
    '''

    protocol_type = Attribute("Protocol type")
    protocol_id = Attribute("Protocol id")
    initiator = Attribute("A message class that initiates the dialog")
    interest_type = Attribute("Type of interest L{InterestType}")

    def __call__(agent, medium, *args, **kwargs):
        '''Creates an instance assuming the interested role.'''


class IInitiator(Interface):
    '''Represent the side of a protocol initiating the dialog.'''

    finish_deferred = Attribute("Deffered which will be fired when the "
                                "dialog is over.")

    def initiate():
        pass


class InitiatorFailed(Exception):
    '''
    The intiating side of the dialog did not finish with successful status
    '''


class IInterested(Interface):
    '''Represent the side of a protocol interested in a dialog.'''

    protocol_id = Attribute("Protocol id")
