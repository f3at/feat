import uuid
from types import NoneType

from twisted.python import components
from zope.interface import implements
from twisted.spread import pb

from feat.agents.base import message, descriptor
from feat.interface.agent import *
from feat.interface.recipient import *
from feat.common import serialization, adapter


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


class BaseRecipient(serialization.Serializable, pb.Copyable):

    def __init__(self, key, shard):
        self._array = [self]
        self._key = key
        self._shard = shard

    def snapshot(self):
        return {"key": self._key, "shard": self._shard}

    def recover(self, snapshot):
        self._key = snapshot["key"]
        self._shard = snapshot["shard"]

    def restored(self):
        self._array = [self]

    @property
    def key(self):
        return self._key

    @property
    def shard(self):
        return self._shard

    def __iter__(self):
        return self._array.__iter__()

    def __hash__(self):
        # VERY important to support recipient as key in a dictionary or a set
        return hash((self._key, self._shard))

    def __eq__(self, other):
        if not isinstance(other, BaseRecipient):
            return NotImplemented
        return (self.type == other.type
                and self.shard == other.shard
                and self.key == other.key)

    def __ne__(self, other):
        if not isinstance(other, BaseRecipient):
            return NotImplemented
        return not self.__eq__(other)

    def __repr__(self):
        return "<Recipient: key=%r, shard=%r>" % (self.key, self.shard, )


@serialization.register
class Recipient(BaseRecipient):

    implements(IRecipient, IRecipients)

    type_name = 'recipient'

    def __init__(self, key, shard=None):
        BaseRecipient.__init__(self, key, shard)

    @property
    def type(self):
        return RecipientType.agent


@serialization.register
class Broadcast(BaseRecipient):

    implements(IRecipient, IRecipients)

    type_name = 'broadcast'

    def __init__(self, protocol_id=None, shard=None):
        BaseRecipient.__init__(self, protocol_id, shard)

    @property
    def type(self):
        return RecipientType.broadcast


@serialization.register
class Recipients(serialization.Serializable, pb.Copyable):

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
        for el1, el2 in zip(self._recipients, other._recipients):
            if el1 != el2:
                return False
        return True

    def __repr__(self):
        cont = ["k=%r,s=%r" % (recp.key, recp.shard, )
                for recp in self._recipients]
        return "<RecipientsList: %s>" % "; ".join(cont)

    def __ne__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return not self.__eq__(other)

    def __iter__(self):
        return self._recipients.__iter__()


components.registerAdapter(Recipients, list, IRecipients)
components.registerAdapter(Recipients, NoneType, IRecipients)


class Agent(Recipient):

    type_name = 'recipient'

    def __init__(self, agent_id, shard=None):
        Recipient.__init__(self, agent_id, shard)


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
        Recipient.__init__(self, message.reply_to.key, message.reply_to.shard)


@adapter.register(descriptor.Descriptor, IRecipient)
@adapter.register(descriptor.Descriptor, IRecipients)
class RecipientFromDescriptor(Recipient):

    type_name = 'recipient'

    def __init__(self, desc):
        BaseRecipient.__init__(self, desc.doc_id, desc.shard)


def dummy_agent():
    '''
    For usage in tests only. Easy way of getting a unique but valid
    recipient.
    '''
    return Agent(str(uuid.uuid1()), 'shard')
