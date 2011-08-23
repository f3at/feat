# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import warnings

from zope.interface import implements

from twisted.internet import reactor
from feat.common import log, defer
from feat.agencies.interface import IMessagingClient
from feat.agents.base import recipient
from feat.agents.base.message import BaseMessage

from feat.agencies.interface import IDialogMessage
from feat.interface.channels import IChannel
from feat.interface.channels import IChannelBinding
from feat.interface.channels import IChannelSink


class FinishConnection(Exception):
    pass


class Connection(log.Logger):

    implements(IMessagingClient, IChannel)

    support_broadcast = True

    def __init__(self, messaging, agent):
        log.Logger.__init__(self, messaging)
        self._messaging = messaging
        self._sink = IChannelSink(agent)

        self._bindings = []
        self._queue = None
        self._disconnected = False
        self._consume_deferred = None

        self._queue_name = agent.get_agent_id()

        self.log_name = self._queue_name

    def initiate(self):
        d = defer.succeed(None)
        if self._queue_name is not None:
            d.addCallback(defer.drop_param,
                          self._messaging.define_queue, self._queue_name)
            d.addCallback(self._main_loop)
        else:
            self.warning('Queue name is None, skipping creating queue '
                         'and consumer.')
        d.addCallback(defer.override_result, self)
        return d

    ### IMessagingClient ###

    def disconnect(self):
        warnings.warn("IMessagingClient's diconnect() is deprecated, "
                      "please use IChannel's release() instead.",
                      DeprecationWarning)
        return self.release()

    def personal_binding(self, key, shard=None):
        warnings.warn("IMessagingClient's personal_binding() is deprecated, "
                      "please use IChannel's bind() instead.",
                      DeprecationWarning)
        return self.bind(key, shard)

    def publish(self, key, shard, message):
        warnings.warn("IMessagingClient's publish() is deprecated, "
                      "please use IChannel's post() instead.",
                      DeprecationWarning)
        return self.post(recipient.Recipient(key=key, route=shard), message)

    ### IChannel ###

    @property
    def channel_type(self):
        return self._messaging.channel_type

    def post(self, recipients, message):
        if not isinstance(message, BaseMessage):
            raise ValueError("Expected second argument to be "
                             "f.a.b.BaseMessage, got %r instead"
                             % (type(message), ))

        recipients = recipient.IRecipients(recipients)

        if IDialogMessage.providedBy(message):
            reply_to = message.reply_to
            if reply_to is None:
                reply_to = recipient.Recipient(self._queue_name,
                                               self._sink.get_shard_id(),
                                               self.channel_type)
                message.reply_to = reply_to
            elif reply_to.channel != self.channel_type:
                self.error("Invalid reply_to for messaging backend, "
                           "dropping %d instance(s) of message: %r",
                           len(list(recipients)), message)
                return

        defers = []
        for recip in recipients:
            assert recip.channel == self.channel_type, \
                   "Unexpected channel type"
            self.log('Sending message to %r', recip)
            d = self._messaging.publish(recip.key, recip.route, message)
            defers.append(d)
        return defer.DeferredList(defers)

    def release(self):
        self._disconnected = True
        if self._consume_deferred and not self._consume_deferred.called:
            ex = FinishConnection("Disconnecting")
            self._consume_deferred.errback(ex)
        return self._messaging.disconnect()

    def bind(self, key, route=None):
        if not route:
            route = self._sink.get_shard_id()
        recip = recipient.Recipient(key=key, route=route)
        return PersonalBinding(self, self._queue_name, recip)

    def get_bindings(self, route=None):
        if route is None:
            return list(self._bindings)
        return [x for x in self._bindings if x.recipient.route == route]

    def get_recipient(self):
        return recipient.Recipient(self._queue_name,
                                   self._sink.get_shard_id())

    ### protected ###

    def _register_binding(self, binding):
        self._bindings.append(binding)

    def _revoke_binding(self, binding):
        self._bindings.remove(binding)

    def _define_exchange(self, route, exchange_type="direct"):
        return self._messaging.define_exchange(route, exchange_type)

    def _create_binding(self, recipient, queue_name):
        return self._messaging.create_binding(recipient.route,
                                              recipient.key,
                                              queue_name)

    def _delete_binding(self, recipient, queue_name):
        return self._messaging.delete_binding(recipient.route,
                                              recipient.key,
                                              queue_name)

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


class BaseBinding(object):

    implements(IChannelBinding)

    def __init__(self, agent_channel, recipient):
        self._channel = agent_channel
        self._recipient = recipient

        self._waiters = []
        self._created = False
        self._failure = None

        self._channel._register_binding(self)

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

    ### IChannelBinding ###

    @property
    def key(self):
        warnings.warn("Bindings' key property is deprecated, "
                      "please use IChannelBinding's recipient instead.",
                      DeprecationWarning)
        return self._recipient.key

    @property
    def shard(self):
        warnings.warn("Bindings' shard property is deprecated, "
                      "please use IChannelBinding's recipient instead.",
                      DeprecationWarning)
        return self._recipient.route

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

    def __init__(self, agent_channel, queue_name, recipient):
        BaseBinding.__init__(self, agent_channel, recipient)
        self._queue_name = queue_name

        d = defer.succeed(None)
        d.addCallback(defer.drop_param, self._channel._define_exchange,
                      self._recipient.route)
        d.addCallback(defer.drop_param, self._channel._create_binding,
                      recipient, queue_name)
        d.addCallbacks(self._on_created, self._on_failed)

    @property
    def created(self):
        warnings.warn("Bindings' created property is deprecated, "
                      "please use IChannelBinding's wait_created() instead.",
                      DeprecationWarning)
        return self.wait_created()

    ### IChannelBinding ###

    def revoke(self):
        d = defer.succeed(None)
        d.addCallback(defer.drop_param, BaseBinding.revoke, self)
        d.addCallback(defer.drop_param, self._channel._delete_binding,
                      self._recipient, self._queue_name)
        return d


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
