from zope.interface import Interface, Attribute

from feat.interface import protocols

__all__ = ["ICollectorFactory", "IAgencyCollector", "IAgentCollector"]


class ICollectorFactory(protocols.IInterest):
    '''This class constructs a notification collector instances implementing
    L{IAgentCollector}. Used when registering interest in notification.
    It is passed as a parameter during registration of interest'''


class IAgencyCollector(Interface):
    '''Agency part of a notification collector. Used by L{IAgentCollector}.'''


class IAgentCollector(protocols.IInterested):
    '''Agent part of the notification collector. Uses a reference
    to L{IAgencyCollector} given at creation time as a medium.'''

    def notified(notification):
        pass
