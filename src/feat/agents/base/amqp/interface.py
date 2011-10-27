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
from zope.interface import Interface


__all__ = ['IAMQPClientFactory', 'IAMQPClient']


class IAMQPClientFactory(Interface):

    def __call__(logger, exchange, exchange_type, host, port, vhost, user,
                 password):
        '''
        Consctructs a labour class that provides sending messages to
        external AMQP exchange.
        @returns: L{IAMQPClient}
        @param logger: L{ILogger}
        @param host: host to connect to (default "localhost")
        @param port: port to connect to (default 5672)
        @param vhost: vhost to connect to (default "/")
        @param user: user to use for authentication (default "guest")
        @param password: password to use for authentication (default "guest")
        @param exchange: name of the exchange (required)
        @param exchange_type: type of exchange to create (default "fanout"),
                              other possible values: direct, topic
        '''


class IAMQPClient(Interface):

    def connect():
        '''
        Connects and creates the destination exchange.
        @returns: Deferred
        '''

    def publish(message, key):
        '''
        Push message.
        @returns: Deferred
        '''

    def disconnect():
        '''
        Close the TCP connection.
        '''
