from zope.interface import Attribute

import protocols, requests


class IRequesterFactory(protocols.IInitiatorFactory):
    '''This class is used to create instances of a requester
    implementing L{IAgentRequester}. Used by the agency when
    initiating a request.'''


class IAgencyRequester(protocols.IAgencyInitiator, requests.IRequestPeer):
    '''Agency part of a requester. Used by L{IAgentRequester} to perform
    the requester role of the request protocol.'''

    replies = Attribute('list of replies received')
    session_id = Attribute('Indentifier of dialog passed in messages')

    def __init__(agent, recipients):
        '''@type agent: L{feat.interface.agency.IAgencyAgent} '''

    def request(request):
        '''Post a request message to specified recipients.
        @param recipients: recipients of the request
        @type  recipients: L{feat.interface.recipient.IRecipient} or list
                of L{feat.interface.recipient.IRecipient}
        '''

    def terminate():
        pass


class IAgentRequester(protocols.IInitiator):
    '''Agent part of the requester. It uses an instance implementing
    L{IAgencyRequester} given at creation time as a medium to perform
    the requester role of the request protocol.'''

    def initiate():
        pass

    def got_reply(reply):
        pass

    def closed():
        """
        Called when the request expire or there is no more reply expected.
        """
