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
import warnings

from zope.interface import implements
from twisted.spread import pb

from feat.agencies import message
from feat.common import serialization, adapter

from feat.interface.agent import IAgent, IAgencyAgent, IDescriptor
from feat.interface.recipient import IRecipient, IRecipients, RecipientType

'''
Provides interfaces for specifing the recipients of messages.
Types that can be passed as destination includes:

- Agent (defined in this module)
- Broadcast (defined in this module)
- agent.IAgencyAgent this helps in tests - one can say that is sending message
                     to the agent
- message.BaseMessage (and subclasses) - one can say he is responding
                                         to message
- descriptor.Descriptor (and subclasses)
- list - the list of any combination of above
'''


class BaseRecipient(serialization.ImmutableSerializable, pb.Copyable):

    def __init__(self, key, route=None):
        self._array = [self]
        self._key = key
        self._route = route

    def snapshot(self):
        return {"key": self._key,
                "route": self._route}

    def recover(self, snapshot):
        self._key = snapshot["key"]
        self._route = snapshot["route"]

    def restored(self):
        self._array = [self]

    @property
    def key(self):
        return self._key

    @property
    def shard(self):
        warnings.warn("Recipient's shard property is deprecated, "
                      "please use route property instead.",
                      DeprecationWarning)
        return self._route

    @property
    def route(self):
        return self._route

    def __iter__(self):
        return self._array.__iter__()

    def __hash__(self):
        # VERY important to support recipient as key in a dictionary or a set
        return hash((self._key, self._route))

    def __eq__(self, other):
        if not isinstance(other, BaseRecipient):
            return NotImplemented
        return (self.type == other.type
                and self.route == other.route
                and self.key == other.key)

    def __ne__(self, other):
        if not isinstance(other, BaseRecipient):
            return NotImplemented
        return not self.__eq__(other)

    def __repr__(self):
        return ("<Recipient: key=%r, route=%r>"
                % (self._key, self._route))


@serialization.register
class Recipient(BaseRecipient):

    implements(IRecipient, IRecipients)

    type_name = 'recipient'

    def __init__(self, key, route=None):
        BaseRecipient.__init__(self, key, route)

    @property
    def type(self):
        return RecipientType.agent


@serialization.register
class Broadcast(BaseRecipient):

    implements(IRecipient, IRecipients)

    type_name = 'broadcast'

    def __init__(self, protocol_id=None, route=None):
        BaseRecipient.__init__(self, protocol_id, route)

    @property
    def type(self):
        return RecipientType.broadcast


@adapter.register(None, IRecipients)
@adapter.register(list, IRecipients)
@serialization.register
class Recipients(serialization.ImmutableSerializable, pb.Copyable):

    implements(IRecipients)

    type_name = 'recipients'

    def __init__(self, recipients):
        self._recipients = []
        recipients = recipients or []
        for recipient in recipients:
            self._recipients.append(IRecipient(recipient))

    def snapshot(self):
        return {"recipients": self._recipients}

    def recover(self, snapshot):
        self._recipients = snapshot["recipients"]

    def remove(self, recp):
        self._recipients.remove(recp)

    def __len__(self):
        return len(self._recipients)

    def __hash__(self):
        return hash(self._recipients)

    def __eq__(self, other):
        if type(self) != type(other):
            return NotImplemented
        for el1, el2 in zip(self._recipients, other._recipients):
            if el1 != el2:
                return False
        return True

    def __repr__(self):
        cont = ["k=%r,r=%r" % (recp.key, recp.route, )
                for recp in self._recipients]
        return "<RecipientsList: %s>" % "; ".join(cont)

    def __ne__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return not self.__eq__(other)

    def __iter__(self):
        return self._recipients.__iter__()


class Agent(Recipient):

    type_name = 'recipient'

    def __init__(self, agent_id, route=None):
        Recipient.__init__(self, agent_id, route)


@adapter.register(IAgent, IRecipient)
@adapter.register(IAgent, IRecipients)
@adapter.register(IAgencyAgent, IRecipient)
@adapter.register(IAgencyAgent, IRecipients)
class RecipientFromAgent(Recipient):

    type_name = 'recipient'

    def __init__(self, agent):
        desc = agent.get_descriptor()
        Recipient.__init__(self, desc.doc_id, desc.shard)


@adapter.register(message.BaseMessage, IRecipient)
@adapter.register(message.BaseMessage, IRecipients)
class RecipientFromMessage(Recipient):

    type_name = 'recipient'

    def __init__(self, message):
        Recipient.__init__(self, message.reply_to.key,
                           message.reply_to.route)


def dummy_agent():
    '''
    For usage in tests only. Easy way of getting a unique but valid
    recipient.
    '''
    return Agent(str(uuid.uuid1()), 'shard')


@adapter.register(IDescriptor, IRecipient)
@adapter.register(IDescriptor, IRecipients)
class RecipientFromDescriptor(Recipient):

    type_name = 'recipient'

    def __init__(self, desc):
        Recipient.__init__(self, desc.doc_id, desc.shard)
