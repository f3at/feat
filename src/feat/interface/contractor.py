from zope.interface import Attribute

from . import protocols, contracts


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

    rejection = Attribute("Contract's rejection message")

    def bid(bid):
        '''Puts a bid on the announcement'''

    def refuse(refusal):
        '''Refuses the announcement'''

    def defect(cancelation):
        '''Cancels the granted job'''

    def finalize(report):
        '''Reports a completed job'''


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
        the contractor has been received. Called only once.'''

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
