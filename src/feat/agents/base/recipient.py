import uuid

from twisted.python import components
from zope.interface import implements

from feat.agents.base import message, descriptor
from feat.interface.agent import *
from feat.interface.recipient import *
from feat.common import serialization


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


class BaseRecipient(serialization.Serializable):

    def __init__(self):
        self._array = [self]

    def restored(self):
        self._array = [self]

    def __iter__(self):
        return self._array.__iter__()

    def __eq__(self, other):
        if not isinstance(other, BaseRecipient):
            return NotImplemented
        return self.type == other.type and\
               self.shard == other.shard and\
               self.key == other.key

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return "<Recipient: key=%r, shard=%r>" % (self.key, self.shard, )


@serialization.register
class Agent(BaseRecipient):

    implements(IRecipient, IRecipients)

    type_name = 'recp'

    def __init__(self, agent_id, shard=None):
        BaseRecipient.__init__(self)
        self.shard = shard
        self.key = agent_id

    @property
    def type(self):
        return RecipientType.agent


@serialization.register
class Broadcast(BaseRecipient):

    implements(IRecipient, IRecipients)

    type_name = 'broadcast'

    def __init__(self, protocol_id=None, shard=None):
        BaseRecipient.__init__(self)
        self.shard = shard
        self.key = protocol_id

    @property
    def type(self):
        return RecipientType.broadcast


@serialization.register
class RecipientFromAgent(BaseRecipient):

    implements(IRecipient, IRecipients)

    type_name = 'recp_a'

    def __init__(self, agent):
        BaseRecipient.__init__(self)
        desc = agent.get_descriptor()
        self.shard = desc.shard
        self.key = desc.doc_id

    @property
    def type(self):
        return RecipientType.agent


components.registerAdapter(RecipientFromAgent, IAgencyAgent, IRecipient)
components.registerAdapter(RecipientFromAgent, IAgencyAgent, IRecipients)


@serialization.register
class RecipientsFromList(serialization.Serializable):

    implements(IRecipients)

    type_name = 'recp_list'

    def __init__(self, llist):
        self.list = []
        for item in llist:
            self.list.append(IRecipient(item))

    def __eq__(self, other):
        for el1, el2 in zip(self.list, other.list):
            if el1 != el2:
                return False

    def __repr__(self):
        cont = ["k=%r,s=%r" % (recp.key, recp.shard, ) for recp in self.list]
        return "<RecipientsList: %s>" % "; ".join(cont)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __iter__(self):
        return self.list.__iter__()


components.registerAdapter(RecipientsFromList, list, IRecipients)


@serialization.register
class RecipientFromMessage(BaseRecipient):
    implements(IRecipient, IRecipients)

    type_name = 'recp_m'

    def __init__(self, message):
        BaseRecipient.__init__(self)
        self.shard = message.reply_to.shard
        self.key = message.reply_to.key

    @property
    def type(self):
        return RecipientType.agent


components.registerAdapter(RecipientFromMessage, message.BaseMessage,
                           IRecipient)
components.registerAdapter(RecipientFromMessage, message.BaseMessage,
                           IRecipients)


@serialization.register
class RecipientFromDescriptor(BaseRecipient):
    implements(IRecipient, IRecipients)

    type_name = 'recp_m'

    def __init__(self, desc):
        BaseRecipient.__init__(self)
        self.shard = desc.shard
        self.key = desc.doc_id

    @property
    def type(self):
        return RecipientType.agent


components.registerAdapter(RecipientFromDescriptor, descriptor.Descriptor,
                           IRecipient)
components.registerAdapter(RecipientFromDescriptor, descriptor.Descriptor,
                           IRecipients)


def dummy_agent():
    '''
    For usage in tests only. Easy way of getting a unique but valid
    recipient.
    '''
    return Agent(str(uuid.uuid1()), 'shard')
