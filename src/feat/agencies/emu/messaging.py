# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from zope.interface import implements
from twisted.internet import defer, reactor
from feat.common import log
from feat.interface.agent import IAgencyAgent

from interface import IConnectionFactory


class Messaging(log.Logger, log.FluLogKeeper):

    implements(IConnectionFactory)

    log_category = "messaging"

    def __init__(self):
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)

        # name -> queue
        self._queues = {}
        # name -> exchange
        self._exchanges = {}

    # IConnectionFactory implementation

    def get_connection(self, agent):
        return Connection(self, agent)

    # end of IConnectionFactory

    def defineExchange(self, name):
        assert name is not None

        exchange = self._getExchange(name)
        if not exchange:
            self.log("Defining exchange: %r" % name)
            exchange = Exchange(name)
            self._exchanges[name] = exchange
        return exchange

    def defineQueue(self, name):
        assert name is not None

        queue = self._getQueue(name)
        if not queue:
            queue = Queue(name)
            self._queues[name] = queue
            self.log("Defining queue: %r" % name)
        return queue

    def publish(self, key, shard, message):
        exchange = self._getExchange(shard)
        if exchange:
            exchange.publish(message, key)
        else:
            self.error("Exchange %r not found!" % shard)

    # private

    def _getExchange(self, name):
        return self._exchanges.get(name, None)

    def _getQueue(self, name):
        return self._queues.get(name, None)


class FinishConnection(Exception):
    pass


class Connection(log.Logger):

    log_category = 'messaging-connection'

    def __init__(self, messaging, agent):
        log.Logger.__init__(self, messaging)
        self._messaging = messaging
        self._agent = IAgencyAgent(agent)

        self._queue = self._messaging.defineQueue(
            self._agent.descriptor.doc_id)
        self._mainLoop(self._queue)
        self._bindings = []

    def _mainLoop(self, queue):

        def rebind(_):
            reactor.callLater(0, bind)

        def stop(reason):
            self.log('Error handler: exiting, reason %r' % reason)

        def bind():
            d = self._consumeQueue(queue)
            d.addCallbacks(rebind, stop)

        bind()

    def _consumeQueue(self, queue):

        def get_and_call_on_message(message):
            # it is important to always lookup the current message handler
            # maybe someone bound callback to it ?
            on_message = self._agent.on_message
            return on_message(message)

        self._consumeDeferred = queue.consume()
        self._consumeDeferred.addCallback(get_and_call_on_message)
        return self._consumeDeferred

    def _append_binding(self, binding):
        self._bindings.append(binding)

    def _remove_binding(self, binding):
        self._bindings.remove(binding)

    # IMessagingClient implementation

    def disconnect(self):
        self._consumeDeferred.errback(FinishConnection("Disconnecting"))

    def personal_binding(self, key, shard=None):
        if not shard:
            shard = self._agent.descriptor.shard
        return PersonalBinding(self, key=key, shard=shard)

    def publish(self, key, shard, message):
        return self._messaging.publish(key, shard, message)

    def get_bindings(self, shard=None):
        if shard:
            return filter(lambda x: x.shard == shard, self._bindings)
        else:
            return self._bindings

    # end of IMessagingClient implementation


class BaseBinding(object):

    def __init__(self, connection, shard, **kwargs):
        self._args = kwargs
        self.connection = connection
        self.connection._append_binding(self)
        self.shard = shard

    def revoke(self):
        self.connection._remove_binding(self)


class PersonalBinding(BaseBinding):

    def __init__(self, connection, shard, key, **kwargs):
        BaseBinding.__init__(self, connection, shard, **kwargs)
        self.key = key
        self.exchange = self.connection._messaging.defineExchange(self.shard)
        self.exchange.bind(self.key, self.connection._queue)

    def revoke(self):
        self.exchange.unbind(self.key, self.connection._queue)
        BaseBinding.revoke(self)


class Queue(object):

    def __init__(self, name):
        self.name = name
        self._messages = []

        self._consumers = []

    def consume(self, *_):
        d = defer.Deferred()
        self._consumers.append(d)
        self._sendMessages()

        return d

    def _sendMessages(self):
        while len(self._messages) > 0 and len(self._consumers) > 0:
            message = self._messages.pop(0)
            consumer = self._consumers.pop(0)
            consumer.callback(message)

    def enqueue(self, message):
        self._messages.append(message)
        reactor.callLater(0, self._sendMessages)


class Exchange(object):

    def __init__(self, name):
        self.name = name
        # key -> [ list of queues ]
        self._bindings = {}

    def bind(self, key, queue):
        assert isinstance(queue, Queue)

        list_for_key = self._bindings.get(key, [])
        if not queue in list_for_key:
            list_for_key.append(queue)
        self._bindings[key] = list_for_key

    def unbind(self, key, queue):
        list_for_key = self._bindings.get(key, [])
        if queue in list_for_key:
            list_for_key.remove(queue)
            if len(list_for_key) == 0:
                del(self._bindings[key])

    def publish(self, message, key):
        assert message is not None
        list_for_key = self._bindings.get(key, [])
        for queue in list_for_key:
            queue.enqueue(message)
