from zope.interface import Interface

import requests


class IReplierFactory(Interface):
    '''This class constructs replier instances implementing
    L{IAgentReplier}. Used upon receiving request messages.
    It is passed as a parameter during registration of interest'''

    def __call__(agent, medium, *args, **kwargs):
        pass


class IAgencyReplier(requests.IRequestPeer):
    '''Agency part of a request replier. Used by L{IAgentReplier} in order
    to perform the replier role in the request protocol.'''

    def reply(reply):
        pass


class IAgentReplier(Interface):
    '''Agent part of the request replier. Uses a reference to L{IAgencyReplier}
    given at creation time as a medium in order to perform the replier role
    in the request protocol.'''

    def requested(request):
        pass
