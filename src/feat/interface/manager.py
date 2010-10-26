from zope.interface import Interface, Attribute

import contracts


class IManagerFactory(Interface):
    '''This class is used to create instances of a contract manager
    implementing L{IAgentManager}.
    Used by the agency when initiating a contract.'''

    def __call__(agency, agent, manager, *args, **kwargs):
        pass

class IAgencyManager(contracts.IContractPeer):
    '''Agency part of a contract manager. Used by L{IAgentManager} to perform
    the manager role of the contract protocol.'''

    bids = Attribute("Contracts's received bids")
    refusals = Attribute("Contract's received refusals")

    def announce(announce):
        pass

    def reject(rejection):
        pass

    def grant(grant):
        pass

    def cancel(cancelation):
        pass

    def acknowledge():
        pass


class IAgentManager(Interface):
    '''Agent part of the contract manager. Use the L{IAgencyManager} given
    at creation time to perform the manager role in the contract protocol.'''

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
