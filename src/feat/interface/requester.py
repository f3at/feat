from zope.interface import Interface, Attribute

import requests


class IRequesterFactory(Interface):
    '''This class is used to create instances of a requester
    implementing L{IAgentRequester}.
    Used by the agency when initiating a request.'''

    def __call__(agency, agent, requester, *args, **kwargs):


class IAgencyRequester(requests.IRequestPeer):
    '''Agency part of a requester. Used by L{IAgentRequester} to perform
    the requester role of the request protocol.'''

    replies = Attribute()

    def request(request):
        pass

    def terminate():
        pass


class IAgentRequester(Interface):
    '''Agent part of the requester. It uses an instance implementing
    L{IAdgencyRequester} given at creation time to perform the requester
    role of the request protocol.'''

    def initiate():
        pass

    def got_reply(reply):
        pass

    def closed():
        """
        Called when the request expire or there is no more reply expected.
        """
