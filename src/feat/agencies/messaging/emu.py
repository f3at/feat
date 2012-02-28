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
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import functools

from zope.interface import implements
from feat.common import log, defer
from feat.agencies.messaging.rabbitmq import Connection, Queue
from feat.agencies.message import BaseMessage

from feat.agencies import common

from feat.agencies.messaging.interface import IMessagingClient


class DirectExchange(object):

    def __init__(self, name):
        self.name = name
        # key -> [ list of queues ]
        self._bindings = {}

    def bind(self, queue, key):
        assert isinstance(queue, Queue)

        list_for_key = self._bindings.get(key, [])
        if not queue in list_for_key:
            list_for_key.append(queue)
        self._bindings[key] = list_for_key

    def unbind(self, queue, key):
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


class FanoutExchange(object):

    def __init__(self, name):
        self.name = name
        # [ list of queues ]
        self._bindings = []

    def bind(self, queue, key=None):
        assert isinstance(queue, Queue), type(Queue)
        if key is not None:
            raise AttributeError("Specified key for fanout exchange. Key: %r" %
                                (key, ))

        if queue not in self._bindings:
            self._bindings.append(queue)

    def unbind(self, queue, key=None):
        if key is not None:
            raise AttributeError("Specified key for fanout exchange. Key: %r" %
                                (key, ))

        try:
            self._bindings.remove(queue)
        except ValueError:
            self.error("Queue %r not bounded too exchange %r" % (queue, self))

    def publish(self, message, key=None):
        assert message is not None
        if key is not None:
            raise AttributeError("Specified key for fanout exchange. Key: %r" %
                                (key, ))

        for queue in self._bindings:
            queue.enqueue(message)


class RabbitMQ(common.ConnectionManager, log.Logger, log.LogProxy,
               common.Statistics):

    implements(IMessagingClient)

    log_category = "emu-rabbitmq"

    exchange_factories = {'fanout': FanoutExchange,
                          'direct': DirectExchange}

    def __init__(self):
        common.ConnectionManager.__init__(self)
        log_keeper = log.get_default() or log.FluLogKeeper()
        log.LogProxy.__init__(self, log_keeper)
        log.Logger.__init__(self, self)
        common.Statistics.__init__(self)

        # name -> queue
        self._queues = {}
        # name -> exchange
        self._exchanges = {}
        self._on_connected()

        self._enabled = True

    ### called by simulation driver ###

    def disable(self):
        self._enabled = False

    def enable(self):
        self._enabled = True

    ### IMessagingClient ###

    def is_idle(self):
        return all(q.is_idle() for q in self._queues.itervalues())

    # is_disconnected() from common.ConnectionManager

    # wait_connected() from common.ConnectionManager

    def disconnect(self):
        # nothing to do here
        pass

    def new_channel(self, sink, queue_name=None):
        return Connection(self, sink, queue_name)

    def connect(self):
        # nothing to do here, in future here implement timouts and/or failures
        pass

    # add_disconnected_cb() from common.ConnectionManager

    # add_reconnected_cb() from common.ConnectionManager

    ### eoi ###

    def define_exchange(self, name, exchange_type=None):
        assert name is not None

        factory = self.exchange_factories[exchange_type]

        exchange = self._get_exchange(name)
        if not exchange:
            self.log("Defining exchange: %r" % name)
            self.increase_stat('exchanges declared')
            exchange = factory(name)
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
        assert isinstance(message, BaseMessage), str(type(message))

        if not self._enabled:
            self.log("RabbitMQ is disabled, message will not be really sent")
            return defer.succeed(message)

        exchange = self._get_exchange(shard)
        if exchange:
            self.increase_stat('messages published')
            exchange.publish(message, key)
        else:
            self.error("Exchange %r not found!" % shard)
        return defer.succeed(message)

    def create_binding(self, exchange, queue, key=None):
        ex = self._get_exchange(exchange)
        if ex is None:
            exchange_type = 'direct' if key is not None else 'fanout'
            ex = self.define_exchange(exchange, exchange_type)
        que = self._get_queue(queue)
        ex.bind(que, key)

    def delete_binding(self, exchange, queue, key=None):
        ex = self._get_exchange(exchange)
        que = self._get_queue(queue)
        ex.unbind(que, key)

    ### private ###

    def _get_exchange(self, name):
        return self._exchanges.get(name, None)

    def _get_queue(self, name):
        return self._queues.get(name, None)
