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
