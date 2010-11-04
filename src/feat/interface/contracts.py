from zope.interface import Interface, Attribute

from feat.common import enum


class ContractState(enum.Enum):
    '''Contract protocol state:

    For manager:
        - announced: For managers, the manager published an announcement
     to contractors.
     - closed: For managers, the contract has been closed because it expired
     or a response has been received from all contractors. For contractors,
     announce expired without putting bid nor refusal.
     - bid: Only for contractors. A bid has been put on an announcement.
     - rejected: Only for contractors. The bid has been rejected by the manager.
     - granted: The contract has been granted to one or multiple contractor.
     - acknowledged: The contract has been acknowledged by the manager.
     - cancelled: The contract got aborted because of one of the peer failure.

    For contractor:
     - announced: The manager published an announcement
     - closed: The Announce expired without putting bid nor refusal.
     - bid: A bid has been put on an announcement.
     - refused: The announce has been refused.
     - rejected: The bid has been rejected by the manager.
     - granted: The contract has been granted.
     - expired: Bid expired without grant nor rejection.
     - completed: Granted job is completed.
     - cancelled: The manager cancelled the granted job.
     - acknowledged: the manager acknowledged the completed job.
     - aborted: The manager has not acknowledged the report in time.
    '''
    (announced, closed, bid, refused, rejected, granted,
     expired, completed, cancelled, acknowledged, aborted) = range(11)


class IContractPeer(Interface):
    '''Define common interface between both peers of the contract protocol.'''

    agent = Attribute("Reference to the owner agent")

    state = Attribute("L{ContractState}")
    announce = Attribute("Contract's announce message")
    grant = Attribute("Contract's grant message")
    report = Attribute("Contract's report message")


