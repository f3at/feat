from zope.interface import Attribute

from feat.interface import protocols, contracts

__all__ = ["IManagerFactory", "IAgencyManager", "IAgentManager"]


class IManagerFactory(protocols.IInitiatorFactory):
    '''This class is used to create instances of a contract manager
    implementing L{IAgentManager}. Used by the agency
    when initiating a contract.'''


class IAgencyManager(contracts.IContractPeer):
    '''Agency part of a contract manager, it is a medium between the agent
    agent and the agency. Used by L{IAgentManager} to perform
    the manager role of the contract protocol.'''

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

    def elect(bid):
        '''
        Mark the bid as elected. Elected bid will get rejected when the
        manager terminates.
        '''

    def cancel(reason):
        '''
        Sends cancellations to all granted or completed contractors
        and terminates.

        @param reason: Optional.
        @type reason: str
        '''

    def terminate():
        '''
        Unregister the listener from the agency. This method is meant to be
        used in nested contracts in case when the whole purpose of the managers
        implemenetation is fetching the bids from nested contractors.
        All the bids which have not been handed over will get rejected.
        '''

    def get_bids():
        '''
        Return list of bids received by the manager from the contractors.
        '''

    def get_recipients():
        '''
        @return: The recipients of the request
        @rtype: IRecipient
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
        '''Called when the final report from all the contractors has been
        received. The result of this method will be put into the Deferred
        obtained with the .notify_finish() method call.

        @param reports: List of all the reports received from the contractors
        '''

    def aborted():
        '''Called when the contractor did not report in time.'''
