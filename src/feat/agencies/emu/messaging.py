# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import functools
import warnings

from zope.interface import implements
from feat.common import log, defer
from feat.agencies.messaging import Connection, Queue
from feat.agencies.interface import IConnectionFactory
from feat.agencies import common

from feat.interface.channels import IBackend


class Messaging(common.ConnectionManager, log.Logger, log.FluLogKeeper,
                common.Statistics):

    implements(IConnectionFactory, IBackend)

    log_category = "emu-messaging"

    channel_type = "default"

    def __init__(self):
        common.ConnectionManager.__init__(self)
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)
        common.Statistics.__init__(self)

        # name -> queue
        self._queues = {}
        # name -> exchange
        self._exchanges = {}
        self._on_connected()

    ### IConnectionFactory ###

    def get_connection(self, agent):
        warnings.warn("IConnectionFactory's get_connection() is deprecated, "
                      "please use IBackend's new_channel() instead.",
                      DeprecationWarning)
        return self.new_channel(agent)

    ### IBackend ####

    def is_idle(self):
        return all(q.is_idle() for q in self._queues.itervalues())

    # is_disconnected() from common.ConnectionManager

    # wait_connected() from common.ConnectionManager

    def disconnect(self):
        # nothing to do here
        pass

    def new_channel(self, agent):
        c = Connection(self, agent)
        return c.initiate()

    # add_disconnected_cb() from common.ConnectionManager

    # add_reconnected_cb() from common.ConnectionManager

    ### eoi ###

    def define_exchange(self, name, exchange_type=None):
        assert name is not None

        exchange = self._get_exchange(name)
        if not exchange:
            self.log("Defining exchange: %r" % name)
            self.increase_stat('exchanges declared')
            exchange = Exchange(name)
            self._exchanges[name] = exchange
        return exchange

    def define_queue(self, name):
        assert name is not None

        queue = self._get_queue(name)
        if not queue:
            self.increase_stat('queues created')
            queue = Queue(name, on_deliver=functools.partial(
                self.increase_stat, 'messages delivered'))

            self._queues[name] = queue
            self.log("Defining queue: %r" % name)
        return queue

    def publish(self, key, shard, message):
        exchange = self._get_exchange(shard)
        if exchange:
            self.increase_stat('messages published')
            exchange.publish(message, key)
        else:
            self.error("Exchange %r not found!" % shard)
        return defer.succeed(message)

    def create_binding(self, exchange, key, queue):
        ex = self._get_exchange(exchange)
        que = self._get_queue(queue)
        ex._bind(key, que)

    def delete_binding(self, exchange, key, queue):
        ex = self._get_exchange(exchange)
        que = self._get_queue(queue)
        ex._unbind(key, que)


    ### private ###

    def _get_exchange(self, name):
        return self._exchanges.get(name, None)

    def _get_queue(self, name):
        return self._queues.get(name, None)


class Exchange(object):

    def __init__(self, name):
        self.name = name
        # key -> [ list of queues ]
        self._bindings = {}

    def _bind(self, key, queue):
        assert isinstance(queue, Queue)

        list_for_key = self._bindings.get(key, [])
        if not queue in list_for_key:
            list_for_key.append(queue)
        self._bindings[key] = list_for_key

    def _unbind(self, key, queue):
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
