from twisted.python import components
from zope.interface import Interface, Attribute, implements

from feat.common import enum
from feat.interface.agent import IAgencyAgent


class RecipientType(enum.Enum):
    agent, broadcast = range(1, 3)


class IRecipients(Interface):
    '''Iterable'''

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
        return self.array.iter()
    

components.registerAdapter(RecipientsFromList, list, IRecipients)
