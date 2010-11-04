from zope.interface import Interface, Attribute

from feat.common import enum


class ContractState(enum.Enum):
    '''Contract protocol state:

    For manager:

     - initiated:    The manager has been initiated but didn't publish any
                      announcement yet.
     - announced:    The manager published an announcement to contractors.
     - closed:       The contract has been closed because the announce expired
                      or a response has been received from all involved
                      contractors.
     - granted:      The contract has been granted to one or multiple
                      contractor.
     - expired:      Contract expire without granting any bid.
     - cancelled:    Some contractor didn't report in time so all contractors
                      got cancelled.
     - acknowledged: All granted jobs have been acknowledged by the manager.
     - aborted:      Some jobs have been cancelled so all the contractors
                      got cancelled.
     - bid:          Only for contractors, invalid state for managers.
     - refused:      Only for contractors, invalid state for managers.
     - rejected:     Only for contractors, invalid state for managers.
     - completed:    Only for contractors, invalid state for managers.

    For contractor:
     - initiated:    The contractor is created, the announce message is not
                      parsed yet.
     - announced:    The manager published an announcement
     - closed:       The Announce expired without putting bid nor refusal.
     - bid:          A bid has been put on an announcement.
     - refused:      The announce has been refused.
     - rejected:     The bid has been rejected by the manager.
     - granted:      The contract has been granted.
     - expired:      Bid expired without grant nor rejection.
     - completed:    Granted job is completed.
     - cancelled:    The manager cancelled the job.
     - acknowledged: The manager acknowledged the completed job.
     - aborted:      The manager has not acknowledged the report in time,
                      or explicitly canceled the job.
    '''
    (initiated, announced, closed, bid, refused, rejected, granted,
     expired, completed, cancelled, acknowledged, aborted) = range(12)


class IContractPeer(Interface):
    '''Define common interface between both peers of the contract protocol.'''

    agent = Attribute("Reference to the owner agent")

    state = Attribute("L{ContractState}")
    announce = Attribute("Contract's announce message")
    grant = Attribute("Contract's grant message")
    report = Attribute("Contract's report message")


