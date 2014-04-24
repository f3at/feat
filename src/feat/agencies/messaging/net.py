# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.
import operator
import os

from feat.extern.txamqp import spec
from feat.extern.txamqp.client import TwistedDelegate, Closed
from feat.extern.txamqp.protocol import AMQClient
from feat.extern.txamqp.content import Content
from feat.extern.txamqp import queue as txamqp_queue
from twisted.internet import reactor, protocol
from zope.interface import implements

from feat.common import log, defer, enum, time, error, container
from feat.common.serialization import banana
from feat.agencies.messaging import debug_message
from feat.agencies.messaging.rabbitmq import Connection, Queue
from feat.agencies.common import StateMachineMixin, ConnectionManager
from feat.agencies.message import BaseMessage

from feat.agencies.messaging.interface import IMessagingClient
from feat.interface.generic import ITimeProvider


class MessagingClient(AMQClient, log.Logger):

    def __init__(self, factory, delegate, vhost, spec, user, password):
        self._factory = factory
        self._user = user
        self._password = password

        log.Logger.__init__(self, factory)
        AMQClient.__init__(self, delegate, vhost, spec, heartbeat=8)

        self._channel_counter = 0

    def connectionMade(self):
        AMQClient.connectionMade(self)
        d = self.authenticate(self._user, self._password)
        d.addCallbacks(defer.drop_param, self._error_handler,
                       callbackArgs=(self._factory.clientConnectionMade, self))

    def connectionLost(self, reason):
        self.log("Connection lost. Reason: %s.", reason)
        AMQClient.connectionLost(self, reason)

    def get_free_channel(self):
        while self._channel_counter in self.channels:
            self._channel_counter += 1
        self.log('Initializing channel: %d', self._channel_counter)
        return self.channel(self._channel_counter)

    def _error_handler(self, fail):
        self.warning('Got error authenticating: %r. Hopefully we will get '
                     'this right during the next reconnection.', fail)


class AMQFactory(protocol.ReconnectingClientFactory, log.Logger, log.LogProxy):

    protocol = MessagingClient
    initialDelay = 0.1
    maxDelay = 30

    def __init__(self, messaging, delegate, user, password,
                 on_connected=None, on_disconnected=None):
        log.Logger.__init__(self, messaging)
        log.LogProxy.__init__(self, messaging)

        self._on_connected = on_connected
        self._on_disconnected = on_disconnected

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
        self.debug('Made connection to RabbitMQ, client: %r', client)
        self.resetDelay()
        self.client = client
        if not self._wait_for_client.called:
            self._wait_for_client.callback(client)
        if callable(self._on_connected):
            self._on_connected()

    def clientConnectionLost(self, connector, reason):
        self._reset_client()
        protocol.ReconnectingClientFactory.clientConnectionLost(\
            self, connector, reason)
        self.debug("Connection to RabbitMQ lost. Host: %s, Port: %d",
                   connector.host, connector.port)

        for cb in self._connection_lost_cbs:
            cb()
        self._connection_lost_cbs = list()
        if callable(self._on_disconnected):
            self._on_disconnected()

    def get_eta_to_reconnect(self):
        if self._callID:
            return time.left(self._callID.getTime())

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

    def is_connected(self):
        return self.client is not None

    def _reset_client(self):
        self.client = None
        self._wait_for_client = defer.Deferred()


class RabbitMQ(ConnectionManager, log.Logger, log.LogProxy):

    implements(IMessagingClient)

    log_category = "net-rabbitmq"

    def __init__(self, host, port, user='guest', password='guest',
                 timeout=5):
        ConnectionManager.__init__(self)
        log.LogProxy.__init__(self, log.get_default() or log.FluLogKeeper())
        log.Logger.__init__(self, self)

        self._user = user
        self._password = password
        self._host = host
        self._port = port
        self._timeout_connecting = timeout

        self._factory = AMQFactory(self, TwistedDelegate(),
                                   self._user, self._password,
                                   on_connected=self._on_connected,
                                   on_disconnected=self._on_disconnected)

    ### public ###

    def reconfigure(self, host, port):
        self.disconnect()
        self._configure(host, port)

    def show_connection_status(self):
        eta = self._factory.get_eta_to_reconnect()
        return "RabbitMQ", self.is_connected(), self._host, self._port, eta

    ### IBackend ####

    def is_idle(self):
        return True

    # is_disconnected() from common.ConnectionManager

    # wait_connected() from common.ConnectionManager

    def disconnect(self):
        self.log("Disconnect called.")
        self._factory.stopTrying()
        self._connector.disconnect()

    def connect(self):
        self._configure(self._host, self._port)
        timeout = self._timeout_connecting
        msg = "Timeout exceeded while trying to connect to messaging server"
        return defer.Timeout(timeout, self.wait_connected(), msg)

    def new_channel(self, agent, queue_name=None):
        d = self._factory.get_client()
        channel_wrapped = Channel(self, d, self._factory)

        return Connection(channel_wrapped, agent, queue_name)

    # add_disconnected_cb() from common.ConnectionManager

    # add_reconnected_cb() from common.ConnectionManager

    ### private ###

    def _configure(self, host, port):
        self._host = host
        self._port = port
        if hasattr(self, '_connector'):
            self._connector.disconnect()
        self._connector = reactor.connectTCP(self._host, self._port,
                                             self._factory)
        self.log('AMQP connector created. Host: %s, Port: %s',
                 self._host, self._port)


class ChannelState(enum.Enum):
    '''
    recording - all calls requiring connection are added to the processing
                chain
    performing - all calls are called instantly
    '''

    (recording, performing) = range(2)


class ProcessingCall(object):

    def __init__(self, method, only_when_connected,
                 remember_between_connections, *args, **kwargs):
        self.method = method
        self.only_when_connected = only_when_connected
        self.remember_between_connections = remember_between_connections
        self.args = args
        self.kwargs = kwargs

        self.callback = defer.Deferred()

    def perform(self):
        d = defer.maybeDeferred(self.method, *self.args, **self.kwargs)
        d.addCallback(defer.keep_param, self.callback.callback)
        d.addErrback(defer.keep_param, self.callback.errback)
        return d


class Channel(log.Logger, log.LogProxy, StateMachineMixin):
    implements(ITimeProvider)

    channel_type = "default"

    def __init__(self, messaging, client_defer, factory):
        StateMachineMixin.__init__(self, ChannelState.recording)
        log.Logger.__init__(self, messaging)
        log.LogProxy.__init__(self, messaging)

        self.channel = None
        self.client = None
        self.factory = factory

        self._queues = []
        self._is_processing = False
        self._processing_chain = []
        self._seen_messages = container.ExpDict(self)
        # holds list of messages to send in case we are disconnected
        self._to_send = container.ExpQueue(self, max_size=50,
                                           on_expire=self._sending_cancelled)

        # RabbitMQ behaviour for creating/deleting bindings has a following
        # issue: if you call create binding two times, and than delete ones
        # there will be no binding. This is a problem for us if two agents
        # create the same binding (public interest) and than one of them
        # deletes is. We need to count the number of creates/deletes to delete
        # the binding only when there is no more agents using it
        self._bindings_count = dict()

        self.serializer = banana.Serializer()
        self.unserializer = banana.Unserializer()

        client_defer.addCallback(self._setup_with_client)

    ### ITimeProvider ###

    def get_time(self):
        return time.time()

    ### Public methods exposed to Connection ###

    def configure_queue(self, queue):
        '''
        Configures the WrappedQueue to receive messages from the client.

        @type queue: L{WrappedQueue}
        '''
        return self._call_on_channel(self._configure_queue, queue)

    def define_queue(self, name):
        self.log('Defining queue: %r', name)

        queue = WrappedQueue(self, name)
        self._queues.append(queue)
        return self.configure_queue(queue)

    def publish(self, key, shard, message):
        if self._cmp_state(ChannelState.recording):
            if message.expiration_time is None:
                self.warning("Ignoring attempt to send a message without the "
                             "expiration time on disconnected channel. "
                             "protocol_id: %s, recipient: %r",
                             message.protocol_id, message.recipient)
                return defer.succeed(None)
            d = defer.Deferred(void_canceller)
            self._to_send.add((key, shard, message, d),
                              message.expiration_time)
            return d
        else:
            return self._publish(key, shard, message)

    def disconnect(self):
        return self._call_on_channel(self._disconnect,
                                     only_when_connected=True)

    def define_exchange(self, name, exchange_type="direct"):
        return self._call_on_channel(self._define_exchange,
                                     name, exchange_type)

    def create_binding(self, exchange, queue, key):
        return self._call_on_channel(self._create_binding,
                                     exchange, key, queue)

    def delete_binding(self, exchange, queue, key):
        return self._call_on_channel(self._delete_binding,
                                     exchange, key, queue)

    def ack(self, message):
        return self._call_on_channel(self._ack, message,
                                     only_when_connected=True,
                                     remember_between_connections=False)

    def parse_message(self, msg):
        result = self.unserializer.convert(msg.content.body)

        if result.message_id in self._seen_messages:
            debug_message(">>>X", result, "DUPLICATED")
            return

        debug_message(">>>>", result)

        self._seen_messages.set(result.message_id, True,
                                expiration=result.expiration_time)
        return result


    ### Private methods operating on the channel ###

    def _configure_queue(self, queue):
        if queue.queue is not None:
            self.debug('Skiping queue %r configuration, because it still '
                       'has the reference to the old queue!', queue.name)
            return defer.succeed(queue)

        d = self.channel.queue_declare(
            queue=queue.name, durable=True, auto_delete=False)
        d.addCallback(defer.drop_param, self.channel.basic_consume,
                      queue=queue.name, no_ack=False)
        d.addCallback(operator.attrgetter('consumer_tag'))
        d.addCallback(self.client.queue)
        d.addCallback(queue.configure)
        return d

    def _publish(self, key, shard, message):
        assert isinstance(message, BaseMessage), "Unexpected message class"
        if message.expiration_time:
            delta = message.expiration_time - time.time()
            if delta < 0:
                debug_message("X<<<", message, "EXPIRED")
                self.log('Not sending expired message. msg=%s, shard=%s, '
                         'key=%s, delta=%r', message, shard, key, delta)
                return

        serialized = self.serializer.convert(message)
        content = Content(serialized)
        content.properties['delivery mode'] = 1  # non-persistent

        self.log('Publishing msg=%s, shard=%s, key=%s', message, shard, key)
        if shard is None:
            debug_message("X<<<", message, "SHARD IS NONE")
            self.error('Tried to send message to exchange=None. This would '
                       'mess up the whole txamqp library state, therefore '
                       'this message is ignored')
            return defer.succeed(None)

        debug_message("<<<<", message)

        d = self.channel.basic_publish(exchange=shard, content=content,
                                       routing_key=key, immediate=False)
        d.addCallback(defer.drop_param, self.channel.tx_commit)
        d.addCallback(defer.override_result, message)
        return d

    def _disconnect(self):
        # Both methods needs to be called. Closes channel locally the other
        # one sends channel close. Yes, it is very bizzare.
        d = self.channel.channel_close()
        d.addCallback(self.channel.close)
        return d

    def _define_exchange(self, name, exchange_type):
        d = self.channel.exchange_declare(
            exchange=name, type=exchange_type, durable=True,
            nowait=False, auto_delete=False)
        return d

    def _create_binding(self, exchange, key, queue):
        exchange_type = 'direct' if key is not None else 'fanout'
        self.log('Creating binding exchange=%s, exchange_type=%s, key=%s, '
                 'queue=%s', exchange, exchange_type, key, queue)
        binding_key = (exchange, key)
        count = self._bindings_count.pop(binding_key, 0)
        self._bindings_count[binding_key] = count + 1

        d = self._define_exchange(exchange, exchange_type)
        d.addCallback(defer.drop_param, self.channel.queue_bind,
                      exchange=exchange, routing_key=key,
                      queue=queue, nowait=False)
        return d

    def _delete_binding(self, exchange, key, queue):
        binding_key = (exchange, key)
        count = self._bindings_count.pop(binding_key, 0)
        if count == 1:
            self.log('Deleting binding exchange=%s, key=%s, queue=%s',
                     exchange, key, queue)
            return self.channel.queue_unbind(
                exchange=exchange, routing_key=key, queue=queue)
        else:
            self.log('Not deleting binding exchange=%s, key=%s, queue=%s '
                     'as it is still used %d times', exchange, key, queue,
                     count)
            self._bindings_count[binding_key] = count - 1
            return defer.succeed(None)

    def _ack(self, message):
        d = defer.succeed(None)
        d.addCallback(defer.drop_param, self.channel.basic_ack,
                      message.delivery_tag)
        d.addCallback(defer.drop_param, self.channel.tx_commit)
        return d

    ### Private methods managing processing chain ###

    def _call_on_channel(self, method, *args, **kwargs):

        only_when_connected = kwargs.pop('only_when_connected', False)
        remember_between_connections = \
                            kwargs.pop('remember_between_connections', True)
        if only_when_connected and self._cmp_state(ChannelState.recording):
            self.log("Ignoring call of %r as currently we are disconnected.",
                     method)
            return
        pc = ProcessingCall(method, only_when_connected,
                            remember_between_connections,
                            *args, **kwargs)
        self._processing_chain.append(pc)
        self.process_next()

        return pc.callback

    def process_next(self):
        if not self._is_processing:
            self._is_processing = True
            d = defer.Deferred()
            d.addCallback(self._process_next)
            d.addBoth(self._finish_processing)
            time.callLater(0, d.callback, None)

    def _finish_processing(self, param):
        self._is_processing = False
        return param

    def _process_next(self, _param):
        if self._cmp_state(ChannelState.recording):
            return

        if len(self._processing_chain) == 0:
            return

        call = self._processing_chain.pop(0)
        self.log('Calling :%r, args: %r, kwargs: %r',
                 call.method.__name__, call.args, call.kwargs)
        d = call.perform()
        d.addCallbacks(self._process_next,
                       self._processing_error_handler,
                       errbackArgs=(call, ))
        return d

    def _processing_error_handler(self, f, call):
        error.handle_failure(
            self, f, 'Failed to perfrom the ProcessingCall. '
            'Method being processed: %r, args: %r, kwargs: %r',
            call.method.__name__, call.args, call.kwargs)
        self._set_state(ChannelState.recording)
        self._processing_chain.insert(0, call)

    def _cleanup_processing_chain(self):
        """Called on reconnection. Removes all the entries which are don't
        have the remember_between_connections flag set"""
        self.log("Removing stale processing chain entries.")
        self._processing_chain = [x for x in self._processing_chain
                                  if x.remember_between_connections]

    def _flush_pending_messages(self):
        d = defer.succeed(None)
        try:
            while True:
                key, shard, message, cb = self._to_send.pop()
                d.addCallback(defer.drop_param, self._publish,
                              key, shard, message)
                d.chainDeferred(cb)
        except container.Empty:
            pass
        finally:
            d.addCallback(defer.override_result, None)
            return d

    def _sending_cancelled(self, entry):
        key, shard, message, cb = entry
        self.log('Message msg=%s, shard=%s, key=%s. Will not be published, '
                 'because it has expired.', message, shard, key)
        cb.cancel()

    ### Private methods managing setup and resetup ###

    def _setup_with_client(self, client):
        if not self._ensure_state(ChannelState.recording):
            return

        self.log("_setup_with_client called, starting channel configuration. "
                 "client=%r", client)

        self.factory.add_connection_lost_cb(self._on_connection_lost)

        def open_channel(channel):
            d = channel.channel_open()
            d.addCallback(lambda _: channel.tx_select())
            d.addCallback(lambda _: channel)
            return d

        def store(channel):
            self.log("Finished channel configuration.")
            self.channel = channel
            self.client = client
            return channel

        def errback(fail):
            self.log("_setup_with_client failed with the error: %r. "
                     "Hopefully we will get this right after the next "
                     "reconnection.", error.get_failure_message(fail))

        d = client.get_free_channel()
        d.addCallback(open_channel)
        d.addCallback(store)
        d.addCallback(self._on_configured)
        d.addErrback(errback)
        return d

    def _on_connection_lost(self):
        self.info("Connection lost")
        self._set_state(ChannelState.recording)

        self.client = None
        self.channel = None
        for queue in self._queues:
            queue.queue = None

        self.factory.add_connection_made_cb(
            ).addCallback(self._setup_with_client)

    def _on_configured(self, _):

        def noop(f):
            # Reason for different error handler here is, that we just
            # want to do nothing. If this request failed, we will get
            # it right after the next reconnection.
            self.log('_configure_queue() call failed with error: %r',
                     f.getErrorMessage())

        def configure(queue):
            d = self._configure_queue(queue)
            d.addErrback(noop)
            return d

        self._cleanup_processing_chain()

        defers = [configure(queue) for queue in self._queues]
        d = defer.DeferredList(defers, consumeErrors=True)
        d.addCallback(defer.drop_param,
                      self._set_state, ChannelState.performing)
        d.addCallback(defer.drop_param, self.process_next)
        d.addCallback(defer.drop_param,
                      self._call_on_channel, self._flush_pending_messages)
        return d


class WrappedQueue(Queue, log.Logger):

    def __init__(self, channel, name):
        log.Logger.__init__(self, channel)
        Queue.__init__(self, name)

        self.channel = channel
        # TimeoutDeferred queue representning instance inside the txAMQP lib
        self.queue = None

    def configure(self, bare_queue):
        if bare_queue is None:
            raise ValueError('Got None, expected TimeoutDeferredQueue.')
        self.log('Configuring queue %r with the instance: %r',
                 self.name, bare_queue)
        self.queue = bare_queue

        self._main_loop()
        return self

    def _main_loop(self, *_):

        def parse_and_enqueue(msg):
            parsed = self.channel.parse_message(msg)
            if parsed is not None:
                self.enqueue(parsed)

        d = self.queue.get()
        d.addCallback(defer.keep_param, parse_and_enqueue)
        d.addCallback(self.channel.ack)
        d.addCallbacks(self._main_loop, self._error_handler)

    def _error_handler(self, f):
        if f.check(Closed, txamqp_queue.Closed):
            self.queue = None
            if self.channel.factory.continueTrying:
                self.log('Queue closed. Waiting to be reconfigured '
                         'with the new queue')
            else:
                self.log("Queue closed cleanly. Terminating")
        else:
            self.error('Unknown exception %r, reraising', f)
            f.raiseException()


def void_canceller(deferred):
    deferred.callback(None)
