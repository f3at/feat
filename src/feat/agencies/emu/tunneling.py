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

from zope.interface import implements

import feat
from feat.agencies import common
from feat.agencies.tunneling import Channel
from feat.common import log, time
from feat.common.serialization import pytree

from feat.interface.channels import IBackend
from feat.interface.recipient import IRecipients, RecipientType


class Backend(common.ConnectionManager, log.Logger, log.FluLogKeeper):

    implements(IBackend)

    log_category = "emu-tunneling"

    channel_type = "tunnel"

    def __init__(self, version=None, bridge=None, registry=None):
        common.ConnectionManager.__init__(self)
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)

        ver = version if version is not None else feat.version
        self._version = int(ver)
        self._bridge = bridge if bridge is not None else Bridge()
        self._registry = registry
        self._channels = {} # {CHANNEL_ID: Channel}
        self._route = "emu://%s" % (uuid.uuid1(), )

        self._bridge.add_backend(self)
        self._on_connected()

    ### public ###

    @property
    def version(self):
        return self._version

    @property
    def route(self):
        return self._route

    def post(self, recipients, message):
        for recip in IRecipients(recipients):
            assert recip.channel == self.channel_type, \
                   "Unexpected channel type"
            if recip.type == RecipientType.broadcast:
                self.warning("Tunneling does not support broadcast "
                             "recipients, dropping message for %r", recip)
                continue
            self._bridge.dispatch(self, recip, message)

    ### IBackend ###

    def is_idle(self):
        return self._bridge.is_idle()

    # is_disconnected() from common.ConnectionManager

    # wait_connected() from common.ConnectionManager

    def disconnect(self):
        self._bridge.remove_backend(self)

    def new_channel(self, agent):
        channel = Channel(self, agent)
        return channel.initiate()

    # add_disconnected_cb() from common.ConnectionManager

    # add_reconnected_cb() from common.ConnectionManager

    ### protected ###

    def _register_channel(self, channel):
        channel_id = channel.channel_id
        assert channel_id not in self._channels, \
               "Channel already registered"
        self._channels[channel_id] = channel

    def _release_channel(self, channel):
        channel_id = channel.channel_id
        assert channel_id in self._channels, \
               "Releasing unknown channel"
        del self._channels[channel_id]

    def _create_serializer(self, to_version):
        return pytree.Serializer(source_ver=self._version,
                                 target_ver=to_version)

    def _create_unserializer(self, from_version):
        return pytree.Unserializer(source_ver=from_version,
                                   target_ver=self._version,
                                   registry=self._registry)

    def _dispatch(self, recip, message):
        if recip.key not in self._channels:
            self.warning("Dropping message to unknown recipient %r", recip)
            return
        self._channels[recip.key]._dispatch(message)


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
        assert backend.route in self._backends, "Removing unknwon backend"
        del self._backends[backend.route]

    def dispatch(self, source_backend, recip, message):
        logger = source_backend

        if recip.route not in self._backends:
            logger.warning("Dropping message to unknown route %r", recip)
            return

        target_backend = self._backends[recip.route]
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
                       target_backend, recip, out_message)

    def _dispatch_message(self, target_backend, recip, message):
        self._pending_calls -= 1
        # Protect against disappearing backends
        if target_backend.route in self._backends:
            if self._backends[target_backend.route] is target_backend:
                target_backend._dispatch(recip, message)
