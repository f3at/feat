from zope.interface import Interface, Attribute


class IInitiatorFactory(Interface):
    '''This class represent a protocol initiator.
    It defines a protocol type, a protocol identifier and can be
    called to create an instance assuming the initiator role of the protocol.
    '''

    protocol_type = Attribute("Protocol type")
    protocol_key = Attribute("Protocol key")

    def __call__(agent, medium, *args, **kwargs):
        '''Creates an instance implementing L{IInitiator}
        assuming the initiator role.'''


class IInterest(Interface):
    '''This class represent an interest in a type of protocol.
    It defines a protocol type, a protocol identifier and can be called
    to create an instance assuming the interested role of the protocol.
    '''

    protocol_type = Attribute("Protocol type")
    protocol_key = Attribute("Protocol key")

    def __call__(agent, medium, *args, **kwargs):
        '''Creates an instance assuming the interested role.'''


class IInitiator(Interface):
    '''Represent the side of a protocol initiating the dialog.'''

    def initiate():
        pass


class IInterested(Interface):
    '''Represent the side of a protocol interested in a dialog.'''
