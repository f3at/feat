import functools

from zope.interface import implements
from twisted.spread import pb

from feat.common import log, defer, first
from feat.common.serialization import banana

from feat.agencies.messaging import routing, debug_message
from feat.agencies.messaging.interface import IChannelBinding
from feat.agencies import common, recipient

from feat.agencies.messaging.interface import ISink, IBackend


class Master(log.Logger, log.LogProxy, common.ConnectionManager,
             pb.Referenceable):

    implements(ISink, IBackend)

    channel_type = 'unix'

    def __init__(self, broker):
        common.ConnectionManager.__init__(self)
        log.LogProxy.__init__(self, broker)
        log.Logger.__init__(self, self)

        self._broker = broker
        self._messaging = None
        # routing key -> SlaveReference
        self._slaves = dict()

        # We do banana over banana ...
        self._serializer = banana.Serializer()
        self._unserializer = banana.Unserializer()

    ### IBackend ###

    def initiate(self, messaging):
        self._messaging = messaging
        self._on_connected()

    def binding_created(self, binding):
        pass

    def binding_removed(self, binding):
        pass

    def create_external_route(self, backend_id, **kwargs):
        pass

    def remove_external_route(self, backend_id, **kwargs):
        pass

    def disconnect(self):
        return defer.succeed(None)

    # is_disconnected() from common.ConnectionManager

    # wait_connected() from common.ConnectionManager

    # add_disconnected_cb() from common.ConnectionManager

    # add_reconnected_cb() from common.ConnectionManager

    ### ISink ###

    def on_message(self, message):
        key = (message.recipient.key, message.recipient.route)
        self.log("Master broker dispatches the message with key: %r", key)
        if key not in self._slaves:
            debug_message("X--M", message, "UNKNOWN KEY")
            self.warning("Don't know what to do, with this message, the key "
                         "is %r, slaves we know: %r",
                         key, self._slaves.keys())
        else:
            debug_message("<--M", message)
            data = self._serializer.convert(message)
            d = [s.dispatch(data) for s in self._slaves[key]]
            return defer.DeferredList(d, consumeErrors=True)

    ### Methods called by Slave ###

    def remote_bind_me(self, slave, key, final=True):
        route = routing.Route(self, key, priority=10, final=final)
        reference = SlaveReference(slave, route)
        cb = functools.partial(self._remove, key)
        slave.notifyOnDisconnect(cb)
        self._append(key, reference)
        self._messaging.append_binding(reference)

    def remote_unbind_me(self, slave, key):
        self._remove(key, slave)

    def remote_dispatch(self, data):
        message = self._unserializer.convert(data)
        debug_message("M-->", message)
        self._messaging.dispatch(message, outgoing=True)

    def remote_create_external_route(self, backend_id, **kwargs):
        return self._messaging.create_external_route(backend_id, **kwargs)

    def remote_remove_external_route(self, backend_id, **kwargs):
        return self._messaging.remove_external_route(backend_id, **kwargs)

    ### private ###

    def _append(self, key, slave):
        if key not in self._slaves:
            self._slaves[key] = list()
        self._slaves[key].append(slave)

    def _remove(self, key, slave):
        if key not in self._slaves:
            self.warning("Tried to remove SlaveReference with a key %r, "
                         "but we don't have this key.", key)
        else:
            found = first(s for s in self._slaves[key]
                          if s.slave == slave)
            if not found:
                self.warning("Tried to remove SlaveReference with a key %r, "
                             "but was not there. Ignoring.", key)
            else:
                self._slaves[key].remove(found)
                self._messaging.remove_binding(found)
            if not self._slaves[key]:
                del(self._slaves[key])


class SlaveReference(object):
    '''Object used internally by Master backend to represent slaves.'''

    implements(IChannelBinding)

    def __init__(self, slave, route):
        assert isinstance(slave, pb.RemoteReference), type(slave)
        assert isinstance(route, routing.Route), type(route)

        self._slave = slave

        self._route = route
        self._recipient = recipient.Agent(*route.key)

    ### IChannelBinding ###

    @property
    def recipient(self):
        return self._recipient

    @property
    def route(self):
        return self._route

    ### public ###

    @property
    def slave(self):
        return self._slave

    @property
    def route(self):
        return self._route

    def dispatch(self, data):
        return self._slave.callRemote('dispatch', data)

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return self._slave == other._slave and self._route == other._route

    def __ne__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return not self.__eq__(other)


class Slave(log.Logger, log.LogProxy, common.ConnectionManager,
            pb.Referenceable):

    implements(ISink, IBackend)

    channel_type = 'unix'

    def __init__(self, broker):
        common.ConnectionManager.__init__(self)
        log.LogProxy.__init__(self, broker)
        log.Logger.__init__(self, self)

        self._broker = broker
        self._messaging = None
        # PBReference to Master137
        self._master = None

        # We do banana over banana ...
        self._serializer = banana.Serializer()
        self._unserializer = banana.Unserializer()

    ### IBackend ###

    def initiate(self, messaging):

        def setter(value):
            self._master = value
            self.log("Got master reference, %r", value)

        self._messaging = messaging
        d = self._broker.get_broker_backend()
        d.addCallback(setter)
        d.addCallback(defer.drop_param, self._on_connected)
        return d

    def binding_created(self, binding):
        route = binding.route.copy(sink=self)
        return self._master.callRemote('bind_me', self, route.key, route.final)

    def binding_removed(self, binding):
        route = binding.route.copy(sink=self)
        return self._master.callRemote('unbind_me', self, route.key)

    def create_external_route(self, backend_id, **kwargs):
        return self._master.callRemote('create_external_route',
                                       backend_id, **kwargs)

    def remove_external_route(self, backend_id, **kwargs):
        return self._master.callRemote('remove_external_route',
                                       backend_id, **kwargs)

    def disconnect(self):
        return defer.succeed(None)

    # is_disconnected() from common.ConnectionManager

    # wait_connected() from common.ConnectionManager

    # add_disconnected_cb() from common.ConnectionManager

    # add_reconnected_cb() from common.ConnectionManager

    ### ISink ###

    def on_message(self, message):
        debug_message("<--S", message)
        data = self._serializer.convert(message)
        return self._master.callRemote('dispatch', data)

    ### Called by Master ###

    def remote_dispatch(self, data):
        message = self._unserializer.convert(data)
        debug_message("S-->", message)
        self._messaging.dispatch(message, outgoing=False)
