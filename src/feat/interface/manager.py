from zope.interface import Attribute

from . import protocols, contracts


class IManagerFactory(protocols.IInitiatorFactory):
    '''This class is used to create instances of a contract manager
    implementing L{IAgentManager}. Used by the agency
    when initiating a contract.'''


class IAgencyManager(contracts.IContractPeer):
    '''Agency part of a contract manager, it is a medium between the agent
    agent and the agency. Used by L{IAgentManager} to perform
    the manager role of the contract protocol.'''

    bids = Attribute("Contracts's received bids")
    refusals = Attribute("Contract's received refusals")

    def announce(announce):
        '''Post an announce message.'''

    def reject(bid, rejection):
        '''
        Reject the message.

        @param bid: The bid message we are rejecting
        @type bid: feat.agents.message.BidMessage
        @param rejection: Optional. Rejection message. It can be constructed by
                          the agency if not specified.
        @type rejection: feat.agents.message.Rejection
        '''

    def grant(grants):
        '''
        Grant the contractor to specified bids. 

        @param grants: Tuple or list of tuples in the format:
                       [(bid1, grant1), (bid2, grant2), ... ]
        '''
               

    def cancel(reason):
        '''
        Sends cancellations to all granted or completed contractors
        and terminates.

        @param reason: Optional.
        @type reason: str
        '''


class IAgentManager(protocols.IInitiator):
    '''Agent part of the contract manager. Use the L{IAgencyManager} given
    at creation time as a medium to perform the manager role
    in the contract protocol.'''

    grant_timeout = Attribute('How long to wait for a grant to be done'
                              'after the announce is closed')
    initiate_timeout = Attribute('How long to wait for initiate method to'
                                 'send announcement')
    announce_timeout = Attribute('How long to wait for incoming bids/refusals'
                                 'before going to closed state')

    def initiate():
        pass

    def refused(refusal):
        pass

    def bid(bid):
        '''Called on each bid received. One may elect to call medium.reject()
        or medium.grant() from this method to close the contract faster'''

    def closed():
        '''Called when the contract expire or there is no more
        bid or refusal expected.'''

    def expired():
        '''Called when the announce has been closed and no grant has
        been done before time specified with the L{grant_timeout} attribute.'''

    def cancelled(cancellation):
        '''The contractor canceled the task.'''

    def completed(reports):
        pass

    def aborted():
        '''Called when the contractor did not report in time.'''









