from zope.interface import Interface, Attribute

import requests


class IRequesterFactory(Interface):

    def __call__(agency, agent, requester, *args, **kwargs):
        pass


class IAgencyRequester(requests.IRequestPeer):

    replies = Attribute()

    def request(request):
        pass

    def terminate():
        pass


class IAgentRequester(Interface):

    def initiate():
        pass

    def got_reply(reply):
        pass

    def closed():
        """
        Called when the request expire or there is no more reply expected.
        """
