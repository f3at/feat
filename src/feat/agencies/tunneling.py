from zope.interface import implements

from feat.agents.base import recipient
from feat.agents.base.message import BaseMessage
from feat.common import log, defer

from feat.agencies.interface import IDialogMessage
from feat.interface.channels import IBackend, IChannel, IChannelSink
from feat.interface.recipient import IRecipients, RecipientType


class Channel(log.Logger):

    implements(IChannel)

    channel_type = "tunnel"

    support_broadcast = False

    def __init__(self, backend, sink):
        log.Logger.__init__(self, backend)
        self._backend = IBackend(backend)
        self._sink = IChannelSink(sink)
        self._connection_string = backend
        backend._register_channel(self._sink.channel_id, self)

    ### IChannel ###

    def release(self):
        self._backend._release_channel(self._sink.channel_id)

    def post(self, recipients, message):
        if not isinstance(message, BaseMessage):
            raise ValueError("Expected second argument to be "
                             "f.a.b.BaseMessage, got %r instead"
                             % (type(message), ))

        if IDialogMessage.providedBy(message):
            reply_to = message.reply_to
            if reply_to is None:
                reply_to = recipient.Recipient(self._sink.channel_id,
                                               "emu", self.channel_type)
                message.reply_to = reply_to
            elif ((reply_to.type is not RecipientType.agent)
                   or (reply_to.channel != self.channel_type)):
                self.error("Invalid reply_to for tunneling, "
                           "dropping %d instance(s) of message: %r",
                           len(list(IRecipients(recipients))), message)
                return

        return self._backend.post(recipients, message)

    def bind(self, key, route=None):
        return None

    def get_bindings(self, route=None):
        return []

    ### protected ###

    def initiate(self):
        return defer.succeed(self)

    def _dispatch(self, message):
        self._sink.on_message(message)
