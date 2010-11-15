from twisted.python import components
from zope.interface import implements

from feat.agents import message
from feat.interface.agent import *
from feat.interface.recipient import *


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


class Agent(object):

    implements(IRecipient, IRecipients)

    def __init__(self, agent_id, shard=None):
        self.type = RecipientType.agent
        self.shard = shard
        self.key = agent_id
        self.array = [self]

    def __iter__(self):
        return self.array.__iter__()


class Broadcast(object):

    implements(IRecipient, IRecipients)

    def __init__(self, protocol_id=None, shard=None):
        self.type = RecipientType.broadcast
        self.shard = shard
        self.key = protocol_id

        self.array = [self]

    def __iter__(self):
        return self.array.__iter__()


class RecipientFromAgent(object):

    implements(IRecipient, IRecipients)

    def __init__(self, agent):
        self.agent = agent
        self.shard = self.agent.descriptor.shard
        self.key = self.agent.descriptor.doc_id

        self.array = [self]

    def __iter__(self):
        return self.array.__iter__()


components.registerAdapter(RecipientFromAgent, IAgencyAgent, IRecipient)
components.registerAdapter(RecipientFromAgent, IAgencyAgent, IRecipients)


class RecipientsFromList(object):

    implements(IRecipients)

    def __init__(self, llist):
        self.array = []
        for item in llist:
            self.array.append(IRecipient(item))

    def __iter__(self):
        return self.array.__iter__()


components.registerAdapter(RecipientsFromList, list, IRecipients)


class RecipientFromMessage(object):
    implements(IRecipient, IRecipients)

    def __init__(self, message):
        self.message = message
        self.shard = self.message.reply_to.shard
        self.key = self.message.reply_to.key

        self.array = [self]

    def __iter__(self):
        return self.array.__iter__()


components.registerAdapter(RecipientFromMessage, message.BaseMessage,
                           IRecipient)
components.registerAdapter(RecipientFromMessage, message.BaseMessage,
                           IRecipients)
