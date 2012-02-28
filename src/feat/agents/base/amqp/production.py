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
from zope.interface import classProvides, implements

from feat.common import serialization, log, defer
from feat.agencies.messaging import net
from feat.agencies import recipient
from feat.agents.application import feat

from feat.agents.base import replay

from feat.agents.base.amqp.interface import IAMQPClientFactory, IAMQPClient
from feat.agencies.messaging.interface import ISink


@feat.register_restorator
class AMQPClient(serialization.Serializable, log.Logger, log.LogProxy):
    classProvides(IAMQPClientFactory)
    implements(IAMQPClient, ISink)

    def __init__(self, logger, exchange, exchange_type='fanout',
                 host='localhost', port=5672, vhost='/',
                 user='guest', password='guest'):
        log.Logger.__init__(self, logger)
        log.LogProxy.__init__(self, logger)
        self._backend = None
        self._connection = None

        self.exchange = exchange
        self.exchange_type = exchange_type
        self.host = host
        self.port = port
        self.vhost = vhost
        self.user = user
        self.password = password

    ### IAMQPClient methods ###

    def connect(self):
        assert self._connection is None
        self._backend = net.RabbitMQ(self.host, self.port,
                                     self.user, self.password)
        self._backend.connect()

        self._channel = self._backend.new_channel(self)
        d = self._channel.initiate()
        d.addCallback(defer.drop_param, self._setup_exchange)
        return d

    def publish(self, message, key):
        assert self._channel is not None
        recip = recipient.Recipient(key, self.exchange)
        return self._channel.post(recip, message)

    @replay.side_effect
    def disconnect(self):
        self._backend.disconnect()
        self._backend = None
        self._channel = None

    ### IChannelSink ###

    def get_agent_id(self):
        return None

    def get_shard_id(self):
        return None

    def on_message(self, msg):
        pass

    ### private ###

    def _setup_exchange(self):
        d = self._channel._define_exchange(self.exchange, self.exchange_type)
        return d

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return self.exchange == other.exchange and\
               self.exchange_type == other.exchange_type and\
               self.host == other.host and\
               self.port == other.port and\
               self.vhost == other.vhost and\
               self.user == other.user and\
               self.password == other.password

    def __ne__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return not self.__eq__(other)
