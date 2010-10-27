from zope.interface import Attribute

import protocols, contracts


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

    def announce(recipients, announce):
        '''Post an announce message to specified recipients.
        @param recipients: recipients of the request
        @type  recipients: L{feat.interface.recipient.IRecipient} or list
                of L{feat.interface.recipient.IRecipient}
        '''

    def reject(rejection):
        pass

    def grant(grant):
        pass

    def cancel(cancelation):
        pass

    def acknowledge():
        pass


class IAgentManager(protocols.IInitiator):
    '''Agent part of the contract manager. Use the L{IAgencyManager} given
    at creation time as a medium to perform the manager role
    in the contract protocol.'''

    def initiate():
        pass

    def refused(refusal):
        pass

    def got_bid(bid):
        pass

    def closed():
        '''Called when the contract expire or there is no more
        bid or refusal expected.'''

    def canceled(cancelation):
        '''The contractor canceled the task.'''

    def updated(update):
        pass

    def finalized(report):
        pass

    def aborted():
        '''Called when the contractor did not report in time.'''
