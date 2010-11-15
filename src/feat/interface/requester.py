from zope.interface import Attribute

from . import protocols, requests

__all__ = ["IRequesterFactory", "IAgencyRequester", "IAgentRequester"]


class IRequesterFactory(protocols.IInitiatorFactory):
    '''This class is used to create instances of a requester
    implementing L{IAgentRequester}. Used by the agency when
    initiating a request.'''


class IAgencyRequester(requests.IRequestPeer):

    '''Agency part of a requester. Used by L{IAgentRequester} to perform
    the requester role of the request protocol.'''

    replies = Attribute('list of replies received')
    session_id = Attribute('Indentifier of dialog passed in messages')

    def request(request):
        '''Post a request message.'''

    def initiate(requester):
        '''
        Called by AgencyAgent to pass the L{IAgentRequester} instance
        and perform all the necesseary setup.
        @param requester: requester instance
        @type requester: L{IAgentRequester}
        '''


class IAgentRequester(protocols.IInitiator):
    '''Agent part of the requester. It uses an instance implementing
    L{IAgencyRequester} given at creation time as a medium to perform
    the requester role of the request protocol.'''

    protocol_id = Attribute('Defines whan particular request it is')
    timeout = Attribute('Number of seconds after which contract expires.\
                         Default=0 means no timeout')

    def initiate():
        pass

    def got_reply(reply):
        pass

    def closed():
        """
        Called when the request expire or there is no more reply expected.
        """
