from zope.interface import Interface, Attribute

from feat.common import enum


class ContractState(enum.Enum):
    none, announced, granted, rejected, acknowledged = range(5)


class IContractPeer(Interface):

    state = Attribute()
    announce = Attribute()
    grant = Attribute()
    report = Attribute()


