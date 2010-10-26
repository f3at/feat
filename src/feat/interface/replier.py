from zope.interface import Interface

import requests


class IReplierFactory(Interface):

    def __call__(agency, agent, replier, *args, **kwargs):
        pass


class IAgencyReplier(requests.IRequestPeer):

    def reply(reply):
        pass


class IAgentReplier(Interface):

    def requested(request):
        pass
