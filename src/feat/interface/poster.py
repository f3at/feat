from zope.interface import Interface, Attribute

from feat.interface import protocols

__all__ = ["IPosterFactory", "IAgencyPoster", "IAgentPoster"]


class IPosterFactory(protocols.IInitiatorFactory):
    '''This class constructs a notification poster instances implementing
    L{IAgentPoster}. Used when initiating protocol.'''


class IAgencyPoster(protocols.IAgencyProtocol):
    '''Agency part of a notification poster. Used by L{IAgentPoster}.'''

    def post(message, recipients=None, expiration_time=None):
        pass


class IAgentPoster(Interface):
    '''Agent part of a notification poster.'''

    notification_timeout = Attribute("Notification expiration timeout.")

    def initiate(*args, **kwargs):
        pass
