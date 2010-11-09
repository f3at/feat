from twisted.python import components
from zope.interface import Interface, Attribute, implements

from feat.common import enum
from feat.interface.agent import IAgencyAgent
from feat.agents import message

'''
Provides interfaces for specifing the recipients of messages. 
Types that can be passed as destination includes:

- Agent (defined in this module)
- Broadcast (defined in this module)
- agent.IAgencyAgent this helps in tests - one can say that is sending message
                     to the agent  
- message.BaseMessage (and subclasses) - one can say he is responding to message
- list - the list of any combination of above
'''

class RecipientType(enum.Enum):
    agent, broadcast = range(1, 3)


class IRecipients(Interface):
    '''Iterable with all elements implementing IRecipient'''

    def __iter__(self):
        pass


class IRecipient(Interface):

    shard = Attribute('Shard of reciepient')
    key = Attribute('Routing key of reciepient')
    type = Attribute('Broadcast or agent?')


class Agent(object):

    implements(IRecipient, IRecipients)

    def __init__(self, agent_id, shard=None):
        self.type = RecipientType.agent
        self.shard = shard
        self.key = agent_id
        self.array = [ self ]

    def __iter__(self):
        return self.array.__iter__()
        

class Broadcast(object):

    implements(IRecipient, IRecipients)

    def __init__(self, protocol_id=None, shard=None):
        self.type = RecipientType.broadcast
        self.shard = shard
        self.key = protocol_id

        self.array = [ self ]

    def __iter__(self):
        return self.array.__iter__()
        

class RecipientFromAgent(object):

    implements(IRecipient, IRecipients)

    def __init__(self, agent):
        self.agent = agent
        self.shard = self.agent.descriptor.shard
        self.key = self.agent.descriptor.uuid

        self.array = [ self ]

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

        self.array = [ self ]

    def __iter__(self):
        return self.array.__iter__()


components.registerAdapter(RecipientFromMessage, message.BaseMessage,
                           IRecipient)
components.registerAdapter(RecipientFromMessage, message.BaseMessage,
                           IRecipients)


