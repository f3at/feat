from zope.interface import implements, classProvides
from feat.interface import contractor
from feat.common import log
from feat.agents import message


class BaseContractor(log.Logger):
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

    def announce_expired(self):
        pass

    def closed(self):
        pass

    def rejected(self, rejection):
        pass

    def granted(self, grant):
        pass

    def bid_expired(self):
        pass

    def cancelled(self, grant):
        pass

    def acknowledged(self, grant):
        pass

    def aborted(self):
        pass
