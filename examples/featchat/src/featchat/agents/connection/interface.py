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

from zope.interface import Interface, Attribute

__all__ = ['IChatServer', 'IChatServerFactory', 'IConnectionAgent']


class IChatServerFactory(Interface):

    def __call__(agent, port_number):
        '''
        @param agent: L{IConnectionAgent}
        @returns: L{IChatServer}
        '''


class IChatServer(Interface):

    port = Attribute('Port the server is listening to.')

    def start():
        '''
        Starts listening.
        '''

    def stop():
        '''
        Disconnects all connections and stops listening.
        '''

    def get_list():
        '''
        Returns dictionary {session_id->ip} of established connections.
        '''

    def broadcast(body):
        '''
        Broadcast message to connected clients.
        '''


class IConnectionAgent(Interface):
    '''Interfaces used by chat component to query for all necessary data.'''

    def validate_session(session_id):
        '''
        Returns True/False indicating if connection should be accepted.
        '''

    def publish_message(body):
        '''
        Notify other connection agent about the message to broadcast.
        '''

    def connection_lost(session_id):
        '''
        Notify agent the authorized connection has been lost.
        '''
