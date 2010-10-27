from zope.interface import Interface, Attribute, implements

from feat.common import enum


class RecipientType(enum.Enum):
    agent, broadcast = range(1, 3)


class IRecipient(Interface):

    shard = Attribute()
    key = Attribute()
    type = Attribute()


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
