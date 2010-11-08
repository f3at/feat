from zope.interface import implements, classProvides
from feat.interface import manager
from feat.common import log
from feat.agents import message


class BaseManager(log.Logger):
    classProvides(manager.IManagerFactory)
    implements(manager.IAgentManager)

    announce = None
    grant = None
    report = None
    agent = None

    log_category = "manager"
    protocol_type = "Contract"
    protocol_id = None

    initiate_timeout = 10
    grant_timeout = 10

    def __init__(self, agent, medium):
        log.Logger.__init__(self, medium)
        
        self.agent = agent
        self.medium = medium

    def initiate(self):
        pass

    def refused(self, refusal):
        pass

    def got_bid(self, bid):
        pass

    def closed(self):
        pass

    def expired(self):
        pass

    def cancelled(self, grant, cancellation):
        pass

    def completed(self, grant, report):
        pass

    def aborted(self, grant):
        pass

