import traceback
import os

from txamqp import spec
from txamqp.client import TwistedDelegate
from txamqp.protocol import AMQClient
from txamqp.content import Content
from twisted.internet import reactor, protocol
from zope.interface import implements
from twisted.internet import defer

from feat.common import log, enum
from feat.agencies.emu.interface import IConnectionFactory
from feat.agencies.emu.messaging import Connection
from feat.agencies.emu.common import StateMachineMixin


class MessagingClient(AMQClient, log.Logger):

    log_category = 'messaging-client'

    def __init__(self, factory, delegate, vhost, spec, user, password):
        self._factory = factory
        self._user = user
        self._password = password

        log.Logger.__init__(self, factory)
        AMQClient.__init__(self, delegate, vhost, spec)

        self._channel_counter = 0

    def connectionMade(self):
        AMQClient.connectionMade(self)
        d = self.authenticate(self._user, self._password)
        d.addErrback(self._error_handler)
        d.addCallback(lambda _: self._factory.clientConnectionMade(self))

    def connectionLost(self, reason):
        self.log("Connection lost. Reason: %s.", reason)
        AMQClient.connectionLost(self, reason)

    def _error_handler(self, e):
        self.error('Failure: %r', e.getErrorMessage())

        frames = traceback.extract_tb(e.getTracebackObject())
        if len(frames) > 0:
            self.error('Last traceback frame: %r', frames[-1])

    def get_free_channel(self):
        while self._channel_counter in self.channels:
            self._channel_counter += 1
        self.log('Initializing channel: %d', self._channel_counter)
        return self.channel(self._channel_counter)


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

        self._reset_client()

    def _reset_client(self):
        self.client = None
        self._wait_for_client = defer.Deferred()

    def buildProtocol(self, addr):
        return self.protocol(self, self._delegate, self._vhost,
                      self._spec, self._user, self._password)

    def clientConnectionMade(self, client):
        self.log('In client connection made, client: %r', client)
        self.client = client
        if not self._wait_for_client.called:
            self._wait_for_client.callback(client)

    def get_client(self):

        def call_and_return(d, ret):
            d.callback(ret)
            return ret

        if self.client:
            return defer.succeed(self.client)
        else:
            d = defer.Deferred()
            self._wait_for_client.addCallback(
                lambda client: call_and_return(d, client))
            return d

    def clientConnectionLost(self, connector, reason):
        self._reset_client()
        protocol.ReconnectingClientFactory.clientConnectionLost(\
            self, connector, reason)
        self.log("Connection lost. Host: %s, Port: %d",
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
        self.log("Disconnect called.")
        self._factory.stopTrying()
        self._connector.disconnect()

    def get_connection(self, agent):
        d = self._factory.get_client()
        channel_wrapped = Channel(self, d)

        return Connection(channel_wrapped, agent)


def wait_for_channel(method):

    def wrapped(self, *args, **kwargs):
        if self.state == ChannelState.recording:
            self.log('Channel not set yet, adding %s call to the '
                     'processing chain', method.__name__)
            return self._append_method_call(method, self, *args, **kwargs)
        else:
            return method(self, *args, **kwargs)

    return wrapped


class ChannelState(enum.Enum):
    '''
    recording - all calls requiring connection are added to the processing
                chain
    performing - all calls are called intantly
    '''

    (recording, performing) = range(2)


class ProcessingCall(object):

    def __init__(self, method, *args, **kwargs):
        self.method = method
        self.args = args
        self.kwargs = kwargs

        self.callback = defer.Deferred()

    def perform(self):
        d = defer.maybeDeferred(self.method, *self.args, **self.kwargs)
        d.addCallback(self.callback.callback)

        return d


class Channel(log.Logger, log.LogProxy, StateMachineMixin):

    log_category = 'messaging-channel'

    def __init__(self, messaging, client_defer):
        StateMachineMixin.__init__(self, ChannelState.recording)
        log.Logger.__init__(self, messaging)
        log.LogProxy.__init__(self, messaging)

        self.channel = None
        self.client = None

        self._processing_chain = []
        self._tag = 0

        client_defer.addCallback(self._setup_with_client)

    def _setup_with_client(self, client):
        self._ensure_state(ChannelState.recording)

        self.log("_setup_with_client called, starting channel configuration. "
                 "client=%r", client)

        def open_channel(channel):
            d = channel.channel_open()
            d.addCallback(lambda _: channel)
            return d

        def store(channel):
            self.log("Finished channel configuration.")
            self.channel = channel
            self.client = client
            return channel

        d = client.get_free_channel()
        d.addCallback(open_channel)
        d.addCallback(store)
        d.addCallback(self._on_configured)
        return d

    def _on_configured(self, _):
        self._set_state(ChannelState.performing)
        self._process_next()

    def _append_method_call(self, method, *args, **kwargs):
        self._ensure_state(ChannelState.recording)

        pc = ProcessingCall(method, *args, **kwargs)
        self._processing_chain.append(pc)
        return pc.callback

    def _process_next(self, *_):
        self._ensure_state(ChannelState.performing)

        if len(self._processing_chain) > 0:
            call = self._processing_chain.pop(0)
            d = call.perform()
            d.addCallbacks(self._process_next, self._processing_error_handler)

    def _processing_error_handler(self, f):
        f.raiseException()
        self.error('Processing failed: %r', f.getErrorMessage())
        self._set_state(ChannelState.recording)

    def _get_tag(self):
        self._tag += 1
        return self._tag

    @wait_for_channel
    def defineQueue(self, name):
        self.log('Defining queue: %r', name)
        tag = "%s-%d" % (name, self._get_tag(), )
        d = self.channel.queue_declare(queue=name, durable=True)
        d.addCallback(lambda _:
                      self.channel.basic_consume(
                          queue=name, no_ack=False, consumer_tag=tag))
        d.addCallback(lambda _:
                      self.client.queue(tag))
        return d

    @wait_for_channel
    def publish(self, key, shard, message):
        assert isinstance(message, str)
        content = Content(message)

        self.log('Publishing msg=%s, shard=%s, key=%s', message, shard, key)
        return self.channel.basic_publish(exchange=shard, content=content,
                                          routing_key=key)

    @wait_for_channel
    def defineExchange(self, name):
        return self.channel.exchange_declare(exchange=name, type="direct",
                                             durable=True, nowait=False)

    @wait_for_channel
    def createBinding(self, exchange, key, queue):
        self.log('Creating binding exchange=%s, key=%s, queue=%s',
                 exchange, key, queue)
        return self.channel.queue_bind(exchange=exchange, routing_key=key,
                                       queue=queue, nowait=False)

    @wait_for_channel
    def deleteBinding(self, exchange, key, queue):
        self.log('Deleting binding exchange=%s, key=%s, queue=%s',
                 exchange, key, queue)
        return self.channel.queue_unbind(exchange=exchange, routing_key=key,
                                         queue=queue)

    def parseMessage(self, msg):
        return msg.content.body
