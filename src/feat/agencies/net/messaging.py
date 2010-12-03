import traceback
import os

from txamqp import spec
from txamqp.client import TwistedDelegate
from txamqp.protocol import AMQClient
from txamqp.content import Content
from txamqp import queue as txamqp_queue
from twisted.internet import reactor, protocol
from zope.interface import implements
from twisted.internet import defer, error

from feat.common import log, enum
from feat.agencies.emu.interface import IConnectionFactory
from feat.agencies.emu.messaging import Connection, Queue
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
    initialDelay = 0.1

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
        self._connection_lost_cbs = list()

    def buildProtocol(self, addr):
        return self.protocol(self, self._delegate, self._vhost,
                      self._spec, self._user, self._password)

    def clientConnectionMade(self, client):
        self.log('In client connection made, client: %r', client)
        self.client = client
        if not self._wait_for_client.called:
            self._wait_for_client.callback(client)

    def clientConnectionLost(self, connector, reason):
        self._reset_client()
        protocol.ReconnectingClientFactory.clientConnectionLost(\
            self, connector, reason)
        self.log("Connection lost. Host: %s, Port: %d",
                 connector.host, connector.port)

        for cb in self._connection_lost_cbs:
            cb()
        self._connection_lost_cbs = list()

    def get_client(self):

        if self.client:
            return defer.succeed(self.client)
        else:
            return self.add_connection_made_cb()

    def add_connection_made_cb(self):

        def call_and_return(d, ret):
            d.callback(ret)
            return ret

        d = defer.Deferred()
        self._wait_for_client.addCallback(
            lambda client: call_and_return(d, client))
        return d

    def add_connection_lost_cb(self, cb):
        if not callable(cb):
            raise AttributeError('Expected callable, got %r instead',
                                 cb.__class__)
        self._connection_lost_cbs.append(cb)

    def _reset_client(self):
        self.client = None
        self._wait_for_client = defer.Deferred()


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
        channel_wrapped = Channel(self, d, self._factory)

        return Connection(channel_wrapped, agent)


def wait_for_channel(method):

    def wrapped(self, *args, **kwargs):
        if self.state == ChannelState.recording:
            self.log('Channel not set yet, adding %s call to the '
                     'processing chain', method.__name__)
            return self._append_method_call(method, self, *args, **kwargs)
        else:
            pc = ProcessingCall(method, self, *args, **kwargs)
            self.log('Calling :%r', method.__name__)
            d = method(self, *args, **kwargs)
            d.addErrback(self._processing_error_handler, pc)
            return d

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

    def __init__(self, messaging, client_defer, factory):
        StateMachineMixin.__init__(self, ChannelState.recording)
        log.Logger.__init__(self, messaging)
        log.LogProxy.__init__(self, messaging)

        self.channel = None
        self.client = None
        self.factory = factory

        self._queues = []
        self._processing_chain = []

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
            self.factory.add_connection_lost_cb(self._on_connection_lost)
            return channel

        d = client.get_free_channel()
        d.addCallback(open_channel)
        d.addCallback(store)
        d.addCallback(self._on_configured)
        return d

    def _on_connection_lost(self):
        self.info("Connection lost")
        self._set_state(ChannelState.recording)

        self.client = None
        self.channel = None
        self.factory.add_connection_made_cb(
            ).addCallback(self._setup_with_client)

    def _on_configured(self, _):
        self._set_state(ChannelState.performing)
        self._process_next()

        for queue in self._queues:
            if queue.queue is not None:
                self.warning('Reconfiguring queue: %r, but it still has the '
                             'reference to the old queue!')
            d = self.get_bare_queue(queue.name)
            d.addCallback(queue.configure)

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
            d.addCallbacks(self._process_next, self._processing_error_handler,
                           errbackArgs=(call, ))

    def _processing_error_handler(self, f, call):
        self.error('Processing failed: %r', f.getErrorMessage())
        self._set_state(ChannelState.recording)
        self._processing_chain.insert(0, call)

    @wait_for_channel
    def get_bare_queue(self, name):
        d = self.channel.queue_declare(queue=name, durable=True)
        d.addCallback(lambda _:
                      self.channel.basic_consume(queue=name, no_ack=False))
        d.addCallback(lambda resp: self.client.queue(resp.consumer_tag))
        return d

    @wait_for_channel
    def defineQueue(self, name):
        self.log('Defining queue: %r', name)

        queue = WrappedQueue(self, name)
        self._queues.append(queue)

        # d = self.get_bare_queue(name)
        # d.addCallback(queue.configure)
        # return d
        return defer.succeed(queue)

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

    @wait_for_channel
    def ack(self, message):
        self.log("Sending ack for the message.")
        return self.channel.basic_ack(message.delivery_tag)

    def parseMessage(self, msg):
        d = self.ack(msg)
        d.addCallback(lambda _: msg.content.body)
        return d


class WrappedQueue(Queue, log.Logger):

    log_category = "messaging-queue"

    def __init__(self, channel, name):
        log.Logger.__init__(self, channel)
        Queue.__init__(self, name)

        self.channel = channel
        self.queue = None

    def configure(self, bare_queue):
        self.log('Configuring queue with the instance: %r', bare_queue)
        self.queue = bare_queue

        self._main_loop()
        return self

    def _main_loop(self, *_):
        d = self.queue.get()
        d.addCallback(self.enqueue)
        d.addCallbacks(self._main_loop, self._error_handler)

    def _error_handler(self, f):
        exception = f.value
        if isinstance(exception, txamqp_queue.Closed):
            if self.channel.factory.continueTrying:
                self.log('Queue closed. Waiting to be reconfigured '
                         'with the new queue')
                self.queue = None
            else:
                self.log("Queue closed cleanly. Terminating")
        else:
            self.error('Unknown exception %r, reraising', f)
            f.raiseException()
