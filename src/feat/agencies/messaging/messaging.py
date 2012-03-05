import uuid

from zope.interface import implements

from feat.common import log, defer, first, container, time, error
from feat.agencies.messaging import routing
from feat.agencies import common, recipient
from feat.agencies.message import BaseMessage

from feat.agencies.messaging.interface import (IChannel, ISink, IBackend,
                                               IChannelBinding)
from feat.interface.recipient import RecipientType
from feat.agencies.interface import IDialogMessage, IFirstMessage
from feat.interface.generic import ITimeProvider


class Channel(log.Logger):

    implements(IChannel, ISink, ITimeProvider)

    support_broadcast = True

    def __init__(self, messaging, agent):
        log.Logger.__init__(self, messaging)
        self._messaging = messaging
        self._agency_agent = agent

        # list of IRecipients we are receiving messages for
        self._bindings = []

        # traversal_id -> True
        self._traversal_ids = container.ExpDict(self)

        # message_id -> True
        self._message_ids = container.ExpDict(self)

    def initiate(self):
        return defer.succeed(self)

    ### IChannel ###

    def post(self, recipients, message):
        if not isinstance(message, BaseMessage):
            raise ValueError("Expected second argument to be "
                             "f.a.b.BaseMessage, got %r instead"
                             % (type(message), ))

        message.message_id = str(uuid.uuid1())
        recipients = recipient.IRecipients(recipients)

        if IDialogMessage.providedBy(message):
            if message.reply_to is None:
                message.reply_to = self._get_own_address()

        for recip in recipients:
            self.log('Sending message to %r', recip)
            msg = message.clone()
            msg.recipient = recip
            self._messaging.dispatch(msg)

    def release(self):
        for binding in self._bindings:
            self.revoke_binding(binding)
        self._messaging.routing.remove_sink(self) # just in case

    def create_binding(self, recp):
        binding = Binding(recp, self)

        # store recipient for our own usage
        self._bindings.append(binding)
        self._messaging.append_binding(binding)
        return binding

    def revoke_binding(self, binding):
        try:
            self._bindings.remove(binding)
        except ValueError:
            self.error("Tried to unregister nonexisting binding")

        self._messaging.remove_binding(binding)

    def get_bindings(self, route=None):
        if route is None:
            return list(self._bindings)
        return [x for x in self._bindings if x.recipient.route == route]

    def create_external_route(self, backend_id, **kwargs):
        self._messaging.create_external_route(backend_id, **kwargs)

    def remove_external_route(self, backend_id, **kwargs):
        self._messaging.remove_external_route(backend_id, **kwargs)

    ### public specific to tunneling ###

    def get_tunneling_url(self):
        return self._messaging.get_tunneling_url()

    ### ISink ###

    def on_message(self, msg):
        '''
        When a message with an already known traversal_id is received,
        we try to build a duplication message and send it in to a protocol
        dependent recipient. This is used in contracts traversing
        the graph, when the contract has reached again the same shard.
        This message is necessary, as silently ignoring the incoming bids
        adds a lot of latency to the nested contracts (it is waiting to receive
        message from all the recipients).
        '''
        self.log('Received message: %r', msg)

        # Check if it isn't expired message
        time_left = time.left(msg.expiration_time)
        if time_left < 0:
            self.log('Throwing away expired message. Time left: %s, '
                     'msg_class: %r', time_left, msg.get_msg_class())
            return False

        # Check for duplicated message
        if msg.message_id in self._message_ids:
            self.log("Throwing away duplicated message %r",
                     msg.get_msg_class())
            return False
        else:
            self._message_ids.set(msg.message_id, True, msg.expiration_time)

        # Check for known traversal ids:
        if IFirstMessage.providedBy(msg):
            t_id = msg.traversal_id
            if t_id is None:
                self.warning(
                    "Received corrupted message. The traversal_id is None ! "
                    "Message: %r", msg)
                return False
            if t_id in self._traversal_ids:
                self.log('Throwing away already known traversal id %r, '
                         'msg_class: %r', t_id, msg.get_msg_class())
                recp = msg.duplication_recipient()
                if recp:
                    resp = msg.duplication_message()
                    self.post(recp, resp)
                return False
            else:
                self._traversal_ids.set(t_id, True, msg.expiration_time)

        # Handle registered dialog
        if IDialogMessage.providedBy(msg):
            recv_id = msg.receiver_id
            if recv_id is not None and \
               recv_id in self._agency_agent._protocols:
                protocol = self._agency_agent._protocols[recv_id]
                protocol.on_message(msg)
                return True

        # Handle new conversation coming in (interest)
        # if msg.protocol_id == 'alert':
        #     print self._agency_agent._interests
        p_type = msg.protocol_type
        if p_type in self._agency_agent._interests:
            p_id = msg.protocol_id
            interest = self._agency_agent._interests[p_type].get(p_id)
            if interest and interest.schedule_message(msg):
                return True

        self.debug("Couldn't find appropriate protocol for message: "
                   "%s", msg.get_msg_class())
        return False

    ### ITimeProvider ###

    def get_time(self):
        return time.time()

    ### private ###

    def _get_own_address(self):
        res = first(x.recipient for x in self._bindings
                    if x.recipient.type == RecipientType.agent)
        if res is None:
            raise ValueError("We have been asked to give the our address "
                             "but so far no personal binding have been "
                             "created.")
        return res


class Messaging(log.Logger, log.LogProxy, common.ConnectionManager):

    def __init__(self, logger):
        common.ConnectionManager.__init__(self)
        log.LogProxy.__init__(self, logger)
        log.Logger.__init__(self, logger)

        self._backends = {} # {CHANNEL_TYPE: IBackend}
        self.routing = routing.Table(self)

        self._pending_dispatches = 0
        self._on_connected()
        self._notifier = defer.Notifier()

    ### public ###

    def get_connection(self, agent):
        c = Channel(self, agent)
        return c.initiate()

    def is_idle(self):
        return self._pending_dispatches == 0

    def dispatch(self, message, outgoing=True):
        self._pending_dispatches += 1
        time.call_next(self._dispatch_internal, message, outgoing)

    ### managing bindings ###

    def append_binding(self, binding):
        # create proper entry in the routing table
        self.routing.append_route(binding.route)
        for backend in self._backends.values():
            backend.binding_created(binding)

    def remove_binding(self, binding):
        self.routing.remove_route(binding.route)
        for backend in self._backends.values():
            backend.binding_removed(binding)

    ### managing backends connected ###

    def add_backend(self, backend, can_become_outgoing=True):
        self.log('Adding backend: %r', backend)
        backend = IBackend(backend)
        self._backends[backend.channel_type] = backend

        backend.add_disconnected_cb(self._on_disconnected)
        backend.add_reconnected_cb(self._check_connections)

        d = defer.succeed(self)
        d.addCallback(backend.initiate)
        d.addErrback(self._add_backend_errback, backend.channel_type)
        d.addCallback(defer.drop_param, self._check_connections)
        if can_become_outgoing and len(self._backends) == 1:
            d.addCallback(defer.drop_param,
                          self.routing.set_outgoing_sink, backend)
        d.addCallback(defer.drop_param, self._notifier.callback,
                      backend.channel_type, backend)
        d.addCallback(defer.override_result, None)
        return d

    def remove_backend(self, backend_id):
        if backend_id not in self._backends:
            self.error("Backend %r not found! Backends now: %r", backend_id,
                       self._backends.keys())
            return
        backend = self._backends.pop(backend_id)
        self.routing.remove_sink(backend)

    def get_backend(self, backend_id):
        back = self._backends.get(backend_id)
        if back is None:
            msg = ("get_backend(%r) called but backends are: %r" %
                   (backend_id, self._backends.keys(), ))
            return defer.Timeout(15, self._notifier.wait(backend_id),
                                 message=msg)
        return back

    def disconnect_backends(self):
        defers = []
        for backend in self._backends.itervalues():
            defers.append(backend.disconnect())
        defers = filter(None, defers)
        if defers:
            d = defer.DeferredList(defers)
        else:
            d = defer.succeed(None)
        return d

    ### Managing external routes ###

    def create_external_route(self, backend_id, **kwargs):
        self._external_route_action('create_external_route', 'creating',
                                    backend_id, **kwargs)

    def remove_external_route(self, backend_id, **kwargs):
        self._external_route_action('remove_external_route', 'removing',
                                    backend_id, **kwargs)

    ### Public query methods ###

    def get_tunneling_url(self):
        return 'tunnel' in self._backends and \
               self._backends['tunnel'].route or None

    def show_connection_status(self):
        if 'rabbitmq' in self._backends:
            return self._backends['rabbitmq'].show_connection_status()

    ### Managing connected status ###

    # _on_disconnected from ConnectionManager

    # _on_connected from ConnectionManager

    def _check_connections(self):
        backends_connected = [b.is_connected()
                              for b in self._backends.itervalues()]
        if not all(backends_connected):
            self._on_disconnected()
        else:
            self._on_connected()

    def _external_route_action(self, _method, _action, backend_id, **kwargs):

        defers = []
        for backend in self._backends.values():
            method = getattr(backend, _method)
            d = defer.maybeDeferred(method, backend_id, **kwargs)
            d.addErrback(defer.print_trace)
            d.addCallback(lambda res: (backend.channel_type, res))
            defers.append(d)

        d = defer.DeferredList(defers, consumeErrors=True)
        d.addCallback(self._external_route_action_cb, _action,
                      backend_id, kwargs)
        return d

    def _external_route_action_cb(self, responses, action,
                                     backend_id, kwargs):
        responses = dict([resp[1] for resp in responses])
        if not any(responses.values()):
            raise ValueError(
                'None of the backends: %r. Reacted to %s the '
                'external route with backend_id: %r kwargs: %r' %
                (responses.keys(), action, backend_id, kwargs))
        responded = [k for k, v in responses.items() if v]
        self.log('Following backends responded to %s external '
                 'route: %r', action, responded)

    ### private ###

    def _dispatch_internal(self, message, outgoing):
        self._pending_dispatches -= 1
        self.routing.dispatch(message, outgoing)

    def _add_backend_errback(self, fail, channel_type):
        error.handle_failure(self, fail, "Failed adding backend %r. "
                             "I will remove it and carry on working.",
                             channel_type)
        self._backends.pop(channel_type, None)


class Binding(object):
    implements(IChannelBinding)

    def __init__(self, recp, owner):
        self.recipient = recp
        self.route = self._create_route(owner)

    ### private ###

    def _create_route(self, sink, priority=0, **kwargs):
        key = (self.recipient.key, self.recipient.route)

        final = kwargs.pop('final', self.recipient.type == RecipientType.agent)
        if kwargs:
            raise AttributeError("Unknown attributes: %r" % (kwargs.keys(), ))
        return routing.Route(sink, key, priority, final)
