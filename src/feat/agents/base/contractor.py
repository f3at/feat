from zope.interface import implements, classProvides
from feat.interface import contractor
from feat.common import log
from feat.agents.base import message


class BaseContractor(log.Logger):
    """
    I am a base class for contractors of contracts.

    @ivar protocol_type: the type of contract this contractor bids on.
                         Must match the type of the manager for this contract;
                         see L{feat.agents.manager.BaseManager}
    @type protocol_type: str
    """
    classProvides(contractor.IContractorFactory)
    implements(contractor.IAgentContractor)

    initiator = message.Announcement

    announce = None
    grant = None
    report = None
    agent = None

    log_category = "contractor"
    protocol_type = "Contract"
    protocol_id = None

    bid_timeout = 10
    ack_timeout = 10

    def __init__(self, agent, medium):
        log.Logger.__init__(self, medium)

        self.agent = agent
        self.medium = medium

    def announced(self, announcement):
        '''@see: L{contractor.IAgentContractor}'''

    def announce_expired(self):
        '''@see: L{contractor.IAgentContractor}'''

    def rejected(self, rejection):
        '''@see: L{contractor.IAgentContractor}'''

    def granted(self, grant):
        '''@see: L{contractor.IAgentContractor}'''

    def bid_expired(self):
        '''@see: L{contractor.IAgentContractor}'''

    def cancelled(self, grant):
        '''@see: L{contractor.IAgentContractor}'''

    def acknowledged(self, grant):
        '''@see: L{contractor.IAgentContractor}'''

    def aborted(self):
        '''@see: L{contractor.IAgentContractor}'''
