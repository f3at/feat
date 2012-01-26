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
import uuid

import feat

from zope.interface import implements

from feat.common import log, defer, time
from feat.common.serialization import pytree

from feat.agencies import common
from feat.agencies.messaging import routing
from feat.web import tunnel

from feat.interface.recipient import RecipientType
from feat.agencies.messaging.interface import ITunnelBackend, IBackend, ISink
from feat.agencies.interface import IDialogMessage


class Tunneling(log.Logger):

    implements(IBackend, ISink)

    channel_type = 'tunnel'

    def __init__(self, backend):
        log.Logger.__init__(self, backend)
        self._backend = ITunnelBackend(backend)

        # Recipient -> Route
        self._routes = dict()

    ### public ###

    @property
    def route(self):
        return self._backend.route

    ### IBackend ###

    def initiate(self, messaging):
        self._messaging = messaging

        self._backend.connect(self)
        return defer.succeed(self)

    def is_idle(self):
        return self._backend.is_idle()

    def is_connected(self):
        return self._backend.is_connected()

    def wait_connected(self):
        return self._backend.wait_connected()

    def disconnect(self):
        self._backend.disconnect()

    def add_disconnected_cb(self, fun):
        self._backend.add_disconnected_cb(fun)

    def add_reconnected_cb(self, fun):
        self._backend.add_reconnected_cb(fun)

    def binding_created(self, binding):
        # not interested
        pass

    def binding_removed(self, binding):
        # not interested
        pass

    def create_external_route(self, backend_id, **kwargs):
        if backend_id != 'tunnel':
            return False
        # notify backend
        uri = kwargs.pop('uri')
        recp = kwargs.pop('recipient')
        self._backend.add_route(recp, uri)

        # create routing so that messages to this agent ends up here
        # instead of being sent through default sink
        routing_key = (recp.key, recp.route, )
        route = routing.Route(self, routing_key, priority=10, final=True)

        if recp in self._routes:
            self.warning("Adding the same route in tunneling for the second "
                         "time for the recipient %r. This might indicate the "
                         "problem, for now I will clean up the old routing "
                         "entry.", recp)
            self._messaging.routing.remove_route(self._routes[recp])
        self._messaging.routing.append_route(route)
        self._routes[recp] = route
        return True

    def remove_external_route(self, backend_id, **kwargs):
        if backend_id != 'tunnel':
            return False
        # notify backend
        recp = kwargs.pop('recipient')
        self._backend.routing.remove_route(recp)

        try:
            self._messaging.routing.remove_route(self._routes[recp])
            del(self._routes[recp])
        except KeyError:
            self.error("remove_external_route() called for the recipient %r "
                       "for which we don't have a route stored", recp)
        return True

    ### ISink ###

    def on_message(self, message):
        return self._backend.post(message)

    ### protected ###

    def _dispatch(self, message):
        self._messaging.dispatch(message, outgoing=False)


class _BaseTunnelBackend(common.ConnectionManager,
                        log.Logger, log.LogProxy):
    '''Abstract base class for tunneling backends.'''

    implements(ITunnelBackend, tunnel.ITunnelDispatcher)

    def __init__(self, version=None, registry=None):
        common.ConnectionManager.__init__(self)
        log.LogProxy.__init__(self, log.get_default() or log.FluLogKeeper())
        log.Logger.__init__(self, self)

        ver = version if version is not None else feat.version
        self._version = int(ver)
        self._registry = registry

        self._channel = None
        self._pending_dispatches = 0
        self._route = None

        # "established connections"
        # Recipient -> route
        self._uris = dict()

    ### public ###

    @property
    def version(self):
        return self._version

    @property
    def route(self):
        return self._route

    ### ITunnelBackend ###

    def post(self, message):
        recip = message.recipient
        if recip.type == RecipientType.broadcast:
            self.warning("Tunneling does not support broadcast "
                         "recipients, dropping message for %r", recip)
            return
        uri = self._uris.get(recip)
        if uri is None:
            raise ValueError(
                "We don't have the URI to connect to agent with "
                "recipient: %r" % (recip, ))
        self._post_message(uri, message)

    def is_idle(self):
        raise NotImplementedError("To be overwritten.")

    def connect(self, channel):
        raise NotImplementedError("To be overwritten.")

    def disconnect(self):
        self._uris.clear()
        self._cleanup()
        self._channel = None

    def add_route(self, recp, uri):
        if recp in self._uris:
            self.debug("Overriting uri for recipient: %r", recp)
        self._uris[recp] = uri

    def remove_route(self, recp):
        r = self._uris.pop(recp, None)
        if r is None:
            self.warning("remove_route() was called for recp %r which we "
                         "don't known. Known at this point: %r",
                         recp, self._uris)

    # is_disconnected() from common.ConnectionManager

    # wait_connected() from common.ConnectionManager

    # add_disconnected_cb() from common.ConnectionManager

    # add_reconnected_cb() from common.ConnectionManager

    ### abstract methods ###

    def _cleanup(self):
        raise NotImplementedError("To be overwritten.")

    def _post_message(self, uri, message):
        raise NotImplementedError("To be overwritten.")

    ### tunnel.ITunnelDispatcher ###

    def dispatch(self, uri, msg):
        self.log('Tunnel received message from uri: %s.', uri)

        self._pending_dispatches += 1

        if IDialogMessage.providedBy(msg):
            recp = msg.reply_to
            self.log("Message is a dialog message, recipient: %r", recp)
            if recp not in self._uris or self._uris[recp] != uri:
                self.debug("Uri not known or doesn't match the recipient, "
                           "registering external route")
                self._channel.create_external_route('tunnel',
                                                    recipient=recp, uri=uri)

        time.call_next(self._dispatch_message, msg)

    ### private ###

    def _dispatch_message(self, message):
        if self._channel is None:
            raise RuntimeError("We are missing the channel reference, "
                               "Backend was not initialized properly. ")
        self._pending_dispatches -= 1
        self._channel._dispatch(message)


class EmuBackend(_BaseTunnelBackend):

    log_category = "emu-tunneling"

    def __init__(self, version=None, bridge=None, registry=None):
        _BaseTunnelBackend.__init__(self, version, registry)

        self._bridge = bridge if bridge is not None else Bridge()
        self._route = "emu://%s" % (str(uuid.uuid1()), )

    def _post_message(self, uri, message):
        self._bridge.dispatch(self, uri, message)

    def is_idle(self):
        return self._pending_dispatches == 0 and self._bridge.is_idle()

    def _cleanup(self):
        if self.is_connected():
            self._bridge.remove_backend(self)

    def connect(self, channel):
        self._channel = channel
        self._bridge.add_backend(self)
        self._on_connected()

    ### protected used by Bridge ###

    def _create_serializer(self, to_version):
        return pytree.Serializer(source_ver=self._version,
                                 target_ver=to_version)

    def _create_unserializer(self, from_version):
        return pytree.Unserializer(source_ver=from_version,
                                   target_ver=self._version,
                                   registry=self._registry)


class Bridge(object):
    """Bridge between tunneling backends."""

    def __init__(self):
        self._backends = {} # {TUNNEL_ROUTE: Backend}
        self._pending_calls = 0

    def is_idle(self):
        return self._pending_calls == 0

    def add_backend(self, backend):
        assert backend.route not in self._backends, "Backend already added"
        self._backends[backend.route] = backend

    def remove_backend(self, backend):
        if backend.route is not None:
            assert backend.route in self._backends, "Removing unknwon backend"
            del self._backends[backend.route]

    def dispatch(self, source_backend, uri, message):
        logger = source_backend

        if uri not in self._backends:
            logger.warning("Dropping message to unknown uri %r", uri)
            return

        target_backend = self._backends[uri]
        source_in_ver = source_backend.version
        target_out_ver = target_backend.version
        is_master = source_in_ver >= target_out_ver
        source_out_ver = target_out_ver if is_master else source_in_ver
        target_in_ver = source_out_ver

        serializer = source_backend._create_serializer(source_out_ver)
        unserializer = target_backend._create_unserializer(target_in_ver)

        out_message = unserializer.convert(serializer.convert(message))

        self._pending_calls += 1
        time.call_next(self._dispatch_message,
                       target_backend, source_backend.route, out_message)

    def _dispatch_message(self, target_backend, uri, message):
        self._pending_calls -= 1
        # Protect against disappearing backends
        if target_backend.route in self._backends:
            if self._backends[target_backend.route] is target_backend:
                target_backend.dispatch(uri, message)


class Backend(_BaseTunnelBackend):

    log_category = "tunneling"

    def __init__(self, host, port_range, version=None, registry=None,
                 server_security_policy=None, client_security_policy=None):
        _BaseTunnelBackend.__init__(self, version, registry)

        t = tunnel.Tunnel(self, port_range, self, public_host=host,
                          version=version, registry=registry,
                          server_security_policy=server_security_policy,
                          client_security_policy=client_security_policy)
        self._tunnel = t

    def _post_message(self, uri, message):
        return self._tunnel.post(uri, message)

    ### ITunnelBackend ###

    def connect(self, channel):
        self._channel = channel
        self._tunnel.start_listening()
        self._route = self._tunnel.uri
        self.info("Listening for tunneling connections on %s", self._route)
        self._on_connected()

    def _cleanup(self):
        self._tunnel.stop_listening()
        self._tunnel.disconnect()

    def is_idle(self):
        return self._pending_dispatches == 0 and self._tunnel.is_idle()
