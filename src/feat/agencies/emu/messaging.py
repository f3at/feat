# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from twisted.internet import defer, reactor
from twisted.python import log


class Messaging(object):
    
    def __init__(self):
        # name -> queue
        self._queues = {}
        # name -> exchange
        self._exchanges = {}

    def _defineExchange(self, name):
        exchange = self._getExchange(name)
        if not exchange:
            log.msg("Defining exchange: %r" % name)
            self._exchanges[name] = Exchange(name)
        return exchange
        
    def _getExchange(name):
        return self.exchanges.get(name, None)

    def createConnection(self, agent):
        return Connection(self, agent)

    def _getQueue(self, name):
        return self._queues.get(name, None)

    def defineQueue(self, name):
        queue = self._getQueue(name)
        if not queue:
            queue = Queue(name)
            self._queues[name] = queue
            log.msg("Defining queue: %r" % name)
        return queue


class Connection(object):
    
    def __init__(self, messaging, agent):
        self._messaging = messaging
        self._agent = agent

        self._queue = self._messaging.defineQueue(self._agent.getId())
        self._mainLoop(self._queue)

    def _mainLoop(self, queue):

        def rebind(_):
            reactor.callLater(0, self._consumeQueue)
     
        def stop(reason):
            log.msg('Error handler: exiting, reason %r' % reason)

        d = self._consumeQueue(queue)
        d.addCallbacks(rebind, stop)

    def _consumeQueue(self, queue):
        self._consumeDeferred = queue.consume()
        self._consumeDeferred.addCallback(self._agent.onMessage)
        return self._consumeDeferred 
        
    def disconnect(self):
        self._consumeDeferred.errback("Disconnecting")


class Queue(object):
    
    def __init__(self, name):
        self.name = name
        self._messages = []

        self._consumers = []

    def consume(self):
        d = defer.Deferred()
        self._consumers.append(d)
        reactor.callLater(0, self._sendMessages)

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
        log.msg('Binding list for the key: %r is now: %r' % (key, list_for_key))

    def unbind(self, key, queue):
        list_for_key = self._bindings.get(key, [])
        if queue in list_for_key:
            list_for_key.remove(queue)
            if len(list_for_key) == 0:
                del(self._bindings[key])
        log.msg('Binding list for the key: %r is now: %r' % (key, list_for_key))

    def publish(self, message, key):
        list_for_key = self._bindings.get(key, [])
        for queue in list_for_key:
            queue.enqueue(message)
            log.msg('Publishing message: %r to the queue: %r' %\
                                                        (message, queue))
