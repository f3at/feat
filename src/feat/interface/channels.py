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
from feat.common import enum

__all__ = ["IBackend", "IChannel", "IChannelBinding", "IChannelSink"]


class IBackend(Interface):

    channel_type = Attribute("Channel name.")

    def is_idle(self):
        """Returns if the backend is idle."""

    def is_connected():
        """Returns the backend is connected."""

    def wait_connected():
        """returns a Deferred fired when the backend got connected."""

    def disconnect():
        """Disonnect the backend."""

    def new_channel(agent):
        """Create a new agent channel."""

    def add_disconnected_cb(fun):
        """Register a function to be called
        when the backend got disconnected."""

    def add_reconnected_cb(fun):
        """Register a function to be called
        when the backend got disconnected."""


class IChannel(Interface):

    support_broadcast = Attribute("If this channel supports"
                                  "broadcast recipients")
    channel_type = Attribute("Channel name.")

    def release():
        """Release agent channel."""

    def post(recipients, message):
        """
        Send message to the specified recipient.
        @type recipients: IRecipients
        @type message: subclass of L{feat.agents.message.BaseMessage}
        """

    def bind(key, route=None):
        """
        Bind the specified key and route to be able to receive messages.
        """

    def get_bindings(route=None):
        """
        Returns the list of binding maintained by the channel.

        @param route: Optional. If specified limits the result to
                      the specified route. If None return all.
        @returns: List of IChannelBinding.
        @rtype: list
        """

    def get_recipient(self):
        """
        Returns the recipient to be used to send a message
        to this channel from outside.
        """


class IChannelBinding(Interface):

    recipient = Attribute("Bound recipient.")

    def wait_created():
        """Returns a deferred called when the bindings is created."""

    def revoke():
        """Revoke binding."""


class IChannelSink(Interface):

    def get_agent_id():
        pass

    def get_shard_id():
        pass

    def on_message(message):
        """Called to process channel's messages."""
