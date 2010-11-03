from zope.interface import Interface, Attribute

from feat.common import enum


class ContractState(enum.Enum):
    '''Contract protocol state:

     - none: Not initiated.
     - announced: The manager has send the announce message to the contractors.
     - closed: The contract has been closed because it expired or a response
       has been recieved from all contractors.
     - bid: Only for contractors. A bid has been send to the manager.
     - rejected: Only for contractors. The bid has been rejected by the manager.
     - granted: The contract has been granted to one or multiple contractor.
     - acknowledged: The contract has been acknowledged by the manager.
     - cancelled: The contract got aborted because of one of the peer failure.
    '''
    (none, announced, closed, bid, rejected,
     granted, acknowledged, cancelled) = range(8)


class IContractPeer(Interface):
    '''Define common interface between both peers of the contract protocol.'''

    agent = Attribute("Reference to the owner agent")

    state = Attribute("L{ContractState}")
    announce = Attribute("Contract's announce message")
    grant = Attribute("Contract's grant message")
    report = Attribute("Contract's report message")


