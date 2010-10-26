from zope.interface import Interface

import contracts


class IContractorFactory(Interface):
    '''This class constructs contactro instance upon receiving announce message.
    It is passed as a parameter during registration of interest'''

    def __call__(agency, agent, contractor, *args, **kwargs):
        pass


class IAgencyContractor(contracts.IContractPeer):
    '''This is a part of interface used by AgentContractor to send messages'''

    rejection = Attribute()

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


class IAgentContractor(Interface):
    '''This is agent part of the cotractor'''

    def announced(announce):
        '''announce is a parsed message'''

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
