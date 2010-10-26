from zope.interface import Interface, Attribute

from feat.common import enum


class RequestState(enum.Enum):
    none, requested, closed = range(3)


class IRequestPeer(Interface):

    state = Attribute()
    request = Attribute()

