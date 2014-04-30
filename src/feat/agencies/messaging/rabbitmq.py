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
from zope.interface import implements

from twisted.internet import reactor
from feat.common import log, defer
from feat.agencies.message import BaseMessage

from feat.agencies.messaging.interface import ISink, IBackend
from feat.agencies import common, recipient


class Sink(log.Logger):

    implements(ISink)

    def __init__(self, logger, routing):
        log.Logger.__init__(self, logger)
        self._routing = routing

    def on_message(self, message):
        self.log("Received message on rabbitmq: %r", message)
        self._routing.dispatch(message, outgoing=False)


class Client(log.Logger, log.LogProxy, common.ConnectionManager):

    implements(ISink, IBackend)

    channel_type = 'rabbitmq'

    log_category = 'rabbitmq-backend'

    def __init__(self, server, queue_name):
        common.ConnectionManager.__init__(self)
        log.LogProxy.__init__(self, server)
        log.Logger.__init__(self, self)

        self._queue_name = queue_name
        self._server = server
        self._channel = None

        # Binding -> PersonalBinding
        self._bindings = dict()

        self._server.add_reconnected_cb(self._on_connected)
        self._server.add_disconnected_cb(self._on_disconnected)

    ### IBackend ###

    def initiate(self, messaging):
        self._messaging = messaging

        if self._server.is_connected():
            self._on_connected()

        incoming_sink = Sink(self, self._messaging)

        self._channel = self._server.new_channel(
            incoming_sink, self._queue_name)
        self._channel.initiate()

        d = defer.succeed(None)
        d.addCallback(defer.drop_param, self._server.connect)
        d.addErrback(self._timeout_connecting)
        d.addCallback(defer.override_result, self)
        return d

    def binding_created(self, binding):
        existing = self._bindings.get(binding)
        if not existing:
            pb = self._channel.bind(
                binding.recipient.route, binding.recipient.key)
            self._bindings[binding] = pb
        pb.refcount += 1

    def binding_removed(self, binding):
        try:
            pb = self._bindings[binding]
        except KeyError:
            self.error("Tried to remove binding which is not registered. %r",
                       binding)
            return
        pb.refcount -= 1
        if pb.refcount == 0:
            pb.revoke()

    def create_external_route(self, backend_id, **kwargs):
        if backend_id == 'rabbitmq':
            host = kwargs.pop('host')
            port = kwargs.pop('port')
            self._server.reconfigure(host, port)
            return True

    def remove_external_route(self, backend_id, **kwargs):
        return False

    def disconnect(self):
        d = defer.succeed(None)
        if self._channel:
            d.addCallback(defer.drop_param, self._channel.release)
        d.addCallback(defer.drop_param, self._server.disconnect)
        return d

    # is_disconnected() from common.ConnectionManager

    # wait_connected() from common.ConnectionManager

    # add_disconnected_cb() from common.ConnectionManager

    # add_reconnected_cb() from common.ConnectionManager

    ### ISink ###

    def on_message(self, message):
        self._channel.post(message.recipient, message)

    ### public ###

    def show_connection_status(self):
        return self._server.show_connection_status()

    ### private ###

    def _timeout_connecting(self, fail):
        fail.trap(defer.TimeoutError)
        self.info("Timeout exceeded while connecting to RabbitMQ server. "
                  "Backend will cary on without the connection and let the "
                  "reconnector handle it... someday.")


class FinishConnection(Exception):
    pass


class Connection(log.Logger):

    support_broadcast = True

    def __init__(self, client, sink, queue_name=None):
        log.Logger.__init__(self, client)
        self._client = client
        self._sink = ISink(sink)

        self._bindings = []
        self._queue = None
        self._disconnected = False
        self._consume_deferred = None

        self._queue_name = queue_name

        self.log_name = self._queue_name

    def initiate(self):
        d = defer.succeed(None)
        if self._queue_name is not None:
            d.addCallback(defer.drop_param,
                          self._client.define_queue, self._queue_name)
            d.addCallback(self._main_loop)
        else:
            self.warning('Queue name is None, skipping creating queue '
                         'and consumer.')
        d.addCallback(defer.override_result, self)
        return d

    ### IChannel ###

    def post(self, recipients, message):
        if not isinstance(message, BaseMessage):
            raise ValueError("Expected second argument to be "
                             "f.a.b.BaseMessage, got %r instead"
                             % (type(message), ))

        recipients = recipient.IRecipients(recipients)

        defers = []
        for recip in recipients:
            self.log('Sending message to %r', recip)
            d = self._client.publish(recip.key, recip.route, message)
            defers.append(d)
        return defer.DeferredList(defers)

    def release(self):
        self._disconnected = True
        if self._consume_deferred and not self._consume_deferred.called:
            ex = FinishConnection("Disconnecting")
            self._consume_deferred.errback(ex)
        return self._client.disconnect()

    def bind(self, route, key=None):
        recip = recipient.Recipient(key=key, route=route)
        exchange_type = 'fanout' if key is None else 'direct'
        return PersonalBinding(self, self._queue_name, recip, exchange_type)

    def get_bindings(self, route=None):
        if route is None:
            return list(self._bindings)
        return [x for x in self._bindings if x.recipient.route == route]

    ### protected ###

    def _register_binding(self, binding):
        self._bindings.append(binding)

    def _revoke_binding(self, binding):
        self._bindings.remove(binding)

    def _define_exchange(self, route, exchange_type="direct"):
        return self._client.define_exchange(route, exchange_type)

    def _create_binding(self, queue_name, route, key=None):
        return self._client.create_binding(route, queue_name, key)

    def _delete_binding(self, recipient, queue_name):
        route = recipient.route
        key = recipient.key
        return self._client.delete_binding(route, queue_name, key)

    ### private ###

    def _main_loop(self, queue):
        self._queue = queue

        def rebind(_):
            reactor.callLater(0, bind)

        def stop(reason):
            if reason.check(FinishConnection):
                self.log('Error handler: exiting, reason %r' % reason)
            else:
                reason.raiseException()

        def bind():
            if self._disconnected:
                return
            d = self._consume_queue(queue)
            d.addCallbacks(rebind, stop)

        bind()

    def _consume_queue(self, queue):

        def get_and_call_on_message(message):
            return self._sink.on_message(message)

        self._consume_deferred = queue.get()
        self._consume_deferred.addCallback(get_and_call_on_message)
        return self._consume_deferred


class Queue(object):

    def __init__(self, name, on_deliver=None):
        self.name = name
        self._messages = []
        self.on_deliver = on_deliver

        self._consumers = []
        self._send_task = None

    def get(self, *_):
        d = defer.Deferred()
        self._consumers.append(d)
        self._schedule_sending()
        return d

    def is_idle(self):
        return not self.has_waiting_consumers() or len(self._messages) == 0 \
               and self._send_task is None

    def has_waiting_consumers(self):
        return len([x for x in self._consumers if not x.called]) > 0

    def enqueue(self, message):
        self._messages.append(message)
        self._schedule_sending()

    def _send_messages(self):
        self._send_task = None
        try:
            while len(self._messages) > 0 and len(self._consumers) > 0:
                consumer = None
                while not (consumer and not consumer.called):
                    consumer = self._consumers.pop(0)
                message = self._messages.pop(0)
                consumer.callback(message)
                if callable(self.on_deliver):
                    self.on_deliver()
        except IndexError:
            # we had consumers but they disconnected,
            # this is expected, just pass
            pass

    def _schedule_sending(self):
        if self._send_task is None:
            self._send_task = reactor.callLater(0, self._send_messages)


class BaseBinding(object):

    def __init__(self, agent_channel, recipient):
        self._channel = agent_channel
        self._recipient = recipient

        self._waiters = []
        self._created = False
        self._failure = None

        self._channel._register_binding(self)

        self.refcount = 0

    ### protected ###

    def _on_created(self, param):
        self._created = True
        for waiter in self._waiters:
            waiter.callback(self)
        self._waiters = None

    def _on_failed(self, failure):
        self._failure = failure
        for waiter in self._waiters:
            waiter.errback(failure)
        self._waiters = None

    @property
    def recipient(self):
        return self._recipient

    def wait_created(self):
        if self._created:
            return defer.succeed(self)
        if self._failure is not None:
            return defer.fail(self._failure)
        d = defer.Deferred()
        self._waiters.append(d)
        return d

    def revoke(self):
        return self._channel._revoke_binding(self)


class PersonalBinding(BaseBinding):

    def __init__(self, agent_channel, queue_name, recipient,
                 exchange_type='direct'):
        BaseBinding.__init__(self, agent_channel, recipient)
        self._queue_name = queue_name

        if exchange_type == 'direct':
            key = recipient.key
        elif exchange_type == 'fanout':
            key = None
        else:
            raise ValueError("Unknown exchange type: %r" % (exchange_type, ))

        d = defer.succeed(None)
        d.addCallback(defer.drop_param, self._channel._create_binding,
                      queue_name, recipient.route, key)
        d.addCallbacks(self._on_created, self._on_failed)

    def revoke(self):
        d = defer.succeed(None)
        d.addCallback(defer.drop_param, BaseBinding.revoke, self)
        d.addCallback(defer.drop_param, self._channel._delete_binding,
                      self._recipient, self._queue_name)
        return d
