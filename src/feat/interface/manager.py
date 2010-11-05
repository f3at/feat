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


    def grant(bid, grant):
        pass

    def cancel(grant, cancelation):
        pass

    def acknowledge(report):
        pass


class IAgentManager(protocols.IInitiator):
    '''Agent part of the contract manager. Use the L{IAgencyManager} given
    at creation time as a medium to perform the manager role
    in the contract protocol.'''

    grant_timeout = Attribute('How long to wait for a grant to be done'
                              'after the announce is closed')

    def initiate():
        pass

    def refused(refusal):
        pass

    def got_bid(bid):
        pass

    def closed():
        '''Called when the contract expire or there is no more
        bid or refusal expected.'''

    def expired():
        '''Called when the announce has been closed and no grant has
        been done before time specified with the L{grant_timeout} attribute.'''

    def canceled(grant, cancelation):
        '''The contractor canceled the task.'''

    def completed(grant, report):
        pass

    def aborted(grant):
        '''Called when the contractor did not report in time.'''
