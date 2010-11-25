import traceback
import os

from txamqp import spec
from txamqp.client import TwistedDelegate
from txamqp.protocol import AMQClient
from twisted.internet import reactor, protocol
from zope.interface import implements

from feat.common import log
from feat.agencies.emu.interface import IConnectionFactory


class MessagingClient(AMQClient, log.Logger):

    log_category = 'messaging-client'

    def __init__(self, factory, delegate, vhost, spec, user, password):
        self._factory = factory
        self._user = user
        self._password = password

        log.Logger.__init__(self, factory)
        AMQClient.__init__(self, delegate, vhost, spec)

    def connectionMade(self):
        AMQClient.connectionMade(self)
        d = self.authenticate(self._user, self._password)
        d.addErrback(self._error_handler)

        # d.addCallback(lambda _: self.channel(1))
        # def store(chan):
        #     self._channel = chan

        # d.addCallback(store)
        # d.addCallback(lambda _: self._channel.channel_open())
        # def msg(_):
        #     print 'Authenticated and opened the channel'
        #     print "%r" % self
        # d.addCallback(msg)

    def connectionLost(self, reason):
        self.log("Connection lost. Reason: %s.", reason)
        AMQClient.connectionLost(self, reason)

    def _error_handler(self, e):
        self.error('Failure: %r', e.getErrorMessage())

        frames = traceback.extract_tb(e.getTracebackObject())
        if len(frames) > 0:
            self.error('Last traceback frame: %r', frames[-1])


class AMQFactory(protocol.ReconnectingClientFactory, log.Logger, log.LogProxy):

    protocol = MessagingClient

    log_category = 'amq-factory'

    def __init__(self, messaging, delegate, user, password):
        log.Logger.__init__(self, messaging)
        log.LogProxy.__init__(self, messaging)

        self._messaging = messaging
        self._user = user
        self._password = password

        self._delegate = delegate
        self._vhost = '/'
        self._spec = spec.load(os.path.join(os.path.dirname(__file__),
                                  'amqp0-8.xml'))

    def buildProtocol(self, addr):
        return self.protocol(self, self._delegate, self._vhost, self._spec,
                             self._user, self._password)

    def clientConnectionLost(self, connector, reason):
        protocol.ReconnectingClientFactory.clientConnectionLost(\
            self, connector, reason)
        self.log("Connection lost.\nHost: %s, Port: %d",
                 connector.host, connector.port)


class Messaging(log.Logger, log.FluLogKeeper):

    implements(IConnectionFactory)

    log_category = "messaging"

    def __init__(self, host, port, user='guest', password='guest'):
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)

        self._host = host
        self._port = port
        self._user = user
        self._password = password

        self._factory = AMQFactory(self, TwistedDelegate(),
                                   self._user, self._password)

        self._connector = reactor.connectTCP(self._host, self._port,
                                             self._factory)

        self.log('Connector created: %r', self._connector)

    def disconnect(self):
        self._factory.stopTrying()
        self._connector.disconnect()
