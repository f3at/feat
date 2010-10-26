from zope.interface import Interface

import contracts


class IContractorFactory(Interface):

    def __call__(agency, agent, contractor, *args, **kwargs):
        pass


class IAgencyContractor(contracts.IContractPeer):

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

    def announced(announce):
        pass

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
