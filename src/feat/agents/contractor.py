from zope.interface import implements, classProvides
from feat.interface import contractor
from feat.common import log
from feat.agents import message


class BaseContractor(log.Logger):
    classProvides(contractor.IContractorFactory)
    implements(contractor.IAgentContractor)

    initiator = message.Announcement

    state = None
    announce = None
    grant = None
    report = None
    agent = None

    log_category = "contractor"
    protocol_type = "Contract"
    protocol_id = None

    grant_wait_timeout = 10

    def __init__(self, agent, medium):
        log.Logger.__init__(self, medium)
        
        self.agent = agent
        self.medium = medium

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


