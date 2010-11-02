from twisted.python import components
from zope.interface import Interface, Attribute, implements

from feat.common import enum
from feat.interface.agent import IAgencyAgent


class RecipientType(enum.Enum):
    agent, broadcast = range(1, 3)


class IRecipient(Interface):

    shard = Attribute('Shard of reciepient')
    key = Attribute('Routing key of reciepient')
    type = Attribute('Broadcast or agent?')


class Agent(object):

    implements(IRecipient)

    def __init__(self, agent_id, shard=None):
        self.type = RecipientType.agent
        self.shard = shard
        self.key = agent_id


class Broadcast(object):

    implements(IRecipient)

    def __init__(self, protocol_id=None, shard=None):
        self.type = RecipientType.broadcast
        self.shard = shard
        self.key = protocol_id

class RecipientFromAgent(object):

    implements(IRecipient)
    
    def __init__(self, agent):
        self.agent = agent
        self.shard = self.agent.descriptor.shard
        self.key = self.agent.descriptor.uuid

components.registerAdapter(RecipientFromAgent, IAgencyAgent, IRecipient)
