# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from zope.interface import implements
from feat.common import log
from feat.agencies.messaging import Connection, Queue
from feat.agencies.interface import IConnectionFactory


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
