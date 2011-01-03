from twisted.python import components
from zope.interface import implements

from feat.agents.base import message
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
- list - the list of any combination of above
'''


class BaseRecipient(serialization.Serializable):

    def __init__(self):
        self.array = [self]

    def __iter__(self):
        return self.array.__iter__()

    def __eq__(self, other):
        if type(self) != type(other):
            return False
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

    def __init__(self, agent_id, shard=None):
        BaseRecipient.__init__(self)
        self.type = RecipientType.agent
        self.shard = shard
        self.key = agent_id


@serialization.register
class Broadcast(BaseRecipient):

    implements(IRecipient, IRecipients)

    def __init__(self, protocol_id=None, shard=None):
        BaseRecipient.__init__(self)
        self.type = RecipientType.broadcast
        self.shard = shard
        self.key = protocol_id


@serialization.register
class RecipientFromAgent(BaseRecipient):

    implements(IRecipient, IRecipients)

    def __init__(self, agent):
        BaseRecipient.__init__(self)
        desc = agent.get_descriptor()
        self.type = RecipientType.agent
        self.shard = desc.shard
        self.key = desc.doc_id


components.registerAdapter(RecipientFromAgent, IAgencyAgent, IRecipient)
components.registerAdapter(RecipientFromAgent, IAgencyAgent, IRecipients)


@serialization.register
class RecipientsFromList(BaseRecipient):

    implements(IRecipients)

    def __init__(self, llist):
        BaseRecipient.__init__(self)
        self.array = []
        for item in llist:
            self.array.append(IRecipient(item))

    def __eq__(self, other):
        for el1, el2 in zip(self.array, other.array):
            if el1 != el2:
                return False

    def __repr__(self):
        cont = ["k=%r,s=%r" % (recp.key, recp.shard, ) for recp in self.array]
        return "<RecipientsList: %s>" % "; ".join(cont)

components.registerAdapter(RecipientsFromList, list, IRecipients)


@serialization.register
class RecipientFromMessage(BaseRecipient):
    implements(IRecipient, IRecipients)

    def __init__(self, message):
        BaseRecipient.__init__(self)
        self.shard = message.reply_to.shard
        self.key = message.reply_to.key


components.registerAdapter(RecipientFromMessage, message.BaseMessage,
                           IRecipient)
components.registerAdapter(RecipientFromMessage, message.BaseMessage,
                           IRecipients)
