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

    def __init__(self, backend, agent):
        log.Logger.__init__(self, backend)
        self._backend = IBackend(backend)
        self._sink = IChannelSink(agent)
        self._channel_id = self._sink.get_agent_id()
        backend._register_channel(self)

    @property
    def channel_id(self):
        return self._channel_id

    ### IChannel ###

    def release(self):
        self._backend._release_channel(self)

    def post(self, recipients, message):
        if not isinstance(message, BaseMessage):
            raise ValueError("Expected second argument to be "
                             "f.a.b.BaseMessage, got %r instead"
                             % (type(message), ))

        if IDialogMessage.providedBy(message):
            reply_to = message.reply_to
            if reply_to is None:
                reply_to = recipient.Recipient(self._sink.get_agent_id(),
                                               self._backend.route,
                                               self.channel_type)
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

    def get_recipient(self):
        return recipient.Recipient(self._channel_id,
                                   self._backend.route,
                                   self._backend.channel_type)

    ### protected ###

    def initiate(self):
        return defer.succeed(self)

    def _dispatch(self, message):
        self._sink.on_message(message)
