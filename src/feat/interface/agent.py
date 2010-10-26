from zope.interface import Interface, Attribute

import logging, journaling


class IAgentFactory(Interface):
    '''Create an agent implementing L{IAgent}. Used by the agency when
    starting an agent.'''

    def __call__(medium, *args, **kwargs):
        pass


class IAgencyAgent(logging.ILogger, journaling.IJournalKeeper):
    '''Agency part of an agent. Used as a medium by the agent
    L{IAgent} implementation.'''

    agency = Attribute("L{IAdgency}")
    shard = Attribute("Shard identifier")
    descriptor = Attribute("Agent descriptor")

    def register_interest(factory, *args, **kwargs):
        '''Registers an interest in a contract or a request.'''

    def revoke_interest(factory):
        '''Revokes any interest in a contract or a request.'''

    def initiate_protocol(factory, *args, **kwargs):
        '''Initiates a contract or a request.'''

    def retrieve_document(id):
        pass

    def update_document(doc):
        pass


class IAgent(Interface):
    '''Agent interface. It uses the L{IAgencyAgent} given at initialization
    time in order to perform its task.'''

    def initiate():
        '''Called after the agent is registered to an agency.'''

    def snapshot():
        '''Called to retrieve the current state of an agent.
        It should return only structures of basic python types
        or instances implementing L{ISerializable}.'''



