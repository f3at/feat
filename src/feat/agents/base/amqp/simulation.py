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
from feat.agents.base.amqp.interface import *
from feat.agents.application import feat

from feat.agents.base import replay


@feat.register_restorator
class AMQPClient(serialization.Serializable, log.Logger, log.LogProxy):
    classProvides(IAMQPClientFactory)
    implements(IAMQPClient)

    def __init__(self, logger, exchange, exchange_type='fanout',
                 host='localhost', port=5672, vhost='/',
                 user='guest', password='guest'):
        log.Logger.__init__(self, logger)
        log.LogProxy.__init__(self, logger)
        self._server = None
        self._connection = None

        self.exchange = exchange
        self.exchange_type = exchange_type
        self.host = host
        self.port = port
        self.vhost = vhost
        self.user = user
        self.password = password

        # key -> messages
        self.messages = dict()

    ### IAMQPClient methods ###

    def connect(self):
        return defer.succeed(None)

    def publish(self, message, key):
        if key not in self.messages:
            self.messages[key] = list()
        self.messages[key].append(message)
        return defer.succeed(None)

    @replay.side_effect
    def disconnect(self):
        pass

    # private

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
