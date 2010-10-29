from zope.interface import Interface, Attribute

import logging, serialization, journaling


class IAgentFactory(Interface):
    '''Create an agent implementing L{IAgent}. Used by the agency when
    starting an agent.'''

    def __call__(medium, *args, **kwargs):
        pass


class IAgencyAgent(logging.ILogKeeper, journaling.IJournalKeeper):
    '''Agency part of an agent. Used as a medium by the agent
    L{IAgent} implementation.'''

    agent = Attribute("L{IAgent}")
    agency = Attribute("L{IAgency}")
    descriptor = Attribute("Agent descriptor")

    def register_interest(factory, *args, **kwargs):
        '''Registers an interest in a contract or a request.'''

    def revoke_interest(factory):
        '''Revokes any interest in a contract or a request.'''

    def initiate_protocol(factory, *args, **kwargs):
        '''
        Initiates a contract or a request.
        @rtype: L{IInitiator}
        @return: Instance of protocols initiator
        '''

    def retrieve_document(id):
        pass

    def update_document(doc):
        pass


class IAgent(serialization.ISerializable):
    '''Agent interface. It uses the L{IAgencyAgent} given at initialization
    time in order to perform its task.'''

    def initiate():
        '''Called after the agent is registered to an agency.'''



