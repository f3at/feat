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


class IMessagingClient(Interface):
    '''
    Interface used by L{IAgencyAgent} to send messages and maintain bindings.
    '''

    def publish(key, shard, message):
        '''
        Send message.

        @param key: Will be passed to the exchange as the routing key.
        @param shard: Identifier of the exchange we are sending message to.
        @param message: Message body.
        @type message: subclass of L{feat.agents.message.BaseMessage}
        '''

    def disconnect():
        '''
        Disconnect client from messaging server.
        '''

    def personal_binding(key, shard):
        '''
        Creates a personal binding (direct binding of the key to personal
        agents queue).

        @param key: Routing key to bind to.
        @param shard: Optional. Shard identifier to bind in. If None uses
                      the agents shard.
        '''

    def get_bindings(shard):
        '''
        Returns the list of binding maintained by the messaging client.

        @param shard: Optional. If specified limits the result to the selected
                      shard. If None return all.
        @returns: List of subclasses of bindings.
        @return_type: list
        '''
