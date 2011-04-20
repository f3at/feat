from zope.interface import Attribute

from feat.interface import protocols, requests

__all__ = ["IRequesterFactory", "IAgencyRequester", "IAgentRequester"]


class IRequesterFactory(protocols.IInitiatorFactory):
    '''This class is used to create instances of a requester
    implementing L{IAgentRequester}. Used by the agency when
    initiating a request.'''


class IAgencyRequester(requests.IRequestPeer):

    '''Agency part of a requester. Used by L{IAgentRequester} to perform
    the requester role of the request protocol.'''

    def request(request):
        '''Post a request message.'''

    def initiate(requester):
        '''
        Called by AgencyAgent to pass the L{IAgentRequester} instance
        and perform all the necesseary setup.
        @param requester: requester instance
        @type requester: L{IAgentRequester}
        '''

    def get_recipients():
        '''
        @return: The recipients of the request
        @rtype: IRecipient
        '''


class IAgentRequester(protocols.IInitiator):
    '''Agent part of the requester. It uses an instance implementing
    L{IAgencyRequester} given at creation time as a medium to perform
    the requester role of the request protocol.'''

    protocol_id = Attribute('Defines whan particular request it is')
    timeout = Attribute('Number of seconds after which contract expires.\
                         Default=0 means no timeout')

    def initiate(*args, **kwargs):
        pass

    def got_reply(reply):
        pass

    def closed():
        """
        Called when the request expire or there is no more reply expected.
        """
