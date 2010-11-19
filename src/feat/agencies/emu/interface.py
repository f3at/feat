# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from zope.interface import Interface


class IListener(Interface):
    '''Represents sth which can be registered in AgencyAgent to
    listen for message'''

    def on_message(message):
        '''hook called when message arrives'''

    def get_session_id():
        '''
        @return: session_id to bound to
        @rtype: string
        '''


class IAgencyInitiatorFactory(Interface):
    '''Factory constructing L{IAgencyInitiator} instance'''


class IAgencyInterestedFactory(Interface):
    '''Factory contructing L{IAgencyInterested} instance'''


class IConnectionFactory(Interface):
    '''
    Responsible for creating connection to external server.
    Should be implemented by database and messaging drivers
    passed to the agency.
    '''

    def get_connection(agent):
        '''
        Instantiate the connection for the agent.

        @params agent: Agent to connect to.
        @type agent: L{feat.interfaces.agent.IAgencyAgent}
        @returns: The connection instance.
        '''
