from zope.interface import Interface


__all__ = ['IAMQPClientFactory', 'IAMQPClient']


class IAMQPClientFactory(Interface):

    def __call__(logger, exchange, exchange_type, host, port, vhost, user,
                 password):
        '''
        Consctructs a labour class that provides sending messages to
        external AMQP exchange.
        @returns: L{IAMQPClient}
        @param logger: L{ILogger}
        @param host: host to connect to (default "localhost")
        @param port: port to connect to (default 5672)
        @param vhost: vhost to connect to (default "/")
        @param user: user to use for authentication (default "guest")
        @param passwrod: password to use for authentication (default "guest")
        @param exchange: name of the exchange (required)
        @param exchange_type: type of exchange to create (default "fanout"),
                              other possible values: direct, topic
        '''


class IAMQPClient(Interface):

    def initiate():
        '''
        Creates the destination exchange.
        @returns: Deferred
        '''

    def publish(message):
        '''
        Push message.
        @returns: Deferred
        '''

    def disconnect():
        '''
        Close the TCP connection.
        '''
