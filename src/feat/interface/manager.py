from zope.interface import Interface, Attribute

import contracts


class IManagerFactory(Interface):

    def __call__(agency, agent, manager, *args, **kwargs):
        '''creates the instance of the agent'''


class IAgencyManager(contracts.IContractPeer):

    bids = Attribute()
    refusals = Attribute()

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

    def initiate():
        pass

    def refused(refusal):
        pass

    def got_bid(bid):
        pass

    def closed():
        """
        Called when the contract expire or there is no more
        bid or refusal expected.
        """

    def canceled(cancelation):
        """
        The contractor canceled the task.
        """

    def updated(update):
        pass

    def finalized(report):
        pass

    def aborted():
        """
        The contractor did not report in time.
        """
