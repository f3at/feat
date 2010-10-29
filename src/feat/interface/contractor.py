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
        pass

    def refuse(refusal):
        pass

    def cancel(cancelation):
        pass

    def update(update):
        pass

    def finalize(report):
        pass


class IAgentContractor(protocols.IInterested):
    '''This is agent part of a contractor. It use a reference to a
    L{IAgencyContractor} given at construction time as a medium in order
    to perform the contractor role of the contract protocol.'''

    def announced(announce):
        '''Called by the agency when a contract matching
        the contractor has been received. Called only once.'''

    def rejected(rejection):
        pass

    def granted(grant):
        pass

    def canceled(grant):
        pass

    def acknowledged(grant):
        pass

    def aborted():
        pass
