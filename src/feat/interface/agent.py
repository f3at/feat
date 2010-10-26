from zope.interface import Interface, Attribute

import logging, journaling


class IAgencyAgent(logging.ILogger, journaling.IJournalKeeper):
    '''Agency part of an agent. Used by the agent L{IAgent} implementation.'''

    agency = Attribute("L{IAdgency}")

    def register(factory, *args, **kwargs):
        '''Registers an interest in a contract or a request.'''

    def revoke(factory):
        '''Revokes any interest in a contract or a request.'''

    def initiate(factory, *args, **kwargs):
        '''Initiates a contract or a request.'''

    def retrieve_document(id):
        pass

    def update_document(doc):
        pass


class IAgent(Interface):

    def init(agency):
        '''Called after the agent is registered to an agency.'''

    def snapshot():
        '''Called to retrieve the current state of an agent.
        It should return only structures of basic python types
        or instances implementing L{ISerializable}.'''



