from zope.interface import Attribute

from feat.interface import protocols, contracts

__all__ = ["IContractorFactory", "IAgencyContractor", "IAgentContractor"]


class IContractorFactory(protocols.IInterest):
    '''This class constructs contractor instance implementing
    L{IAgentContractor}. Used upon receiving announce messages.
    It is passed as a parameter during registration of interest'''

    def __call__(agent, medium, *args, **kwargs):
        pass


class IAgencyContractor(contracts.IContractPeer):
    '''This is the agency part of a contractor, the medium between the agent
    and the agency. It is used by L{IAgentContractor} implementations
    to perform the contractor role of the contract protocol'''

    def bid(bid):
        '''Puts a bid on the announcement'''

    def handover(bid):
        '''
        Sends the bid received from the nested contractor. The reply-to field
        is preserved, so the rest of dialog will be delegated to the nested
        contractor. For us this means end of story.
        '''

    def refuse(refusal):
        '''Refuses the announcement'''

    def defect(cancellation):
        '''Cancels the granted job'''

    def finalize(report):
        '''Reports a completed job'''

    def update_manager_address(recipient):
        '''Call it to notify the agency that manager is available now
        at different address.'''


class IAgentContractor(protocols.IInterested):
    '''This is agent part of a contractor. It use a reference to a
    L{IAgencyContractor} given at construction time as a medium in order
    to perform the contractor role of the contract protocol.'''

    ack_timeout = Attribute('How long to wait for ack after sending'
                            'the report before aborting')
    bid_timeout = Attribute('How long to wait for grant or rejection '
                            'after putting the bid')

    def announced(announce):
        '''Called by the agency when a contract matching
        the contractor has been received. Called only once.

        @type  announce: L{feat.agents.message.Announcement}
        '''

    def announce_expired():
        pass

    def rejected(rejection):
        pass

    def granted(grant):
        pass

    def bid_expired():
        pass

    def cancelled(grant):
        pass

    def acknowledged(grant):
        pass

    def aborted():
        pass
