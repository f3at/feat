from zope.interface import implements, classProvides
from feat.interface import manager
from feat.common import log


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
    announce_timeout = 10
    grant_timeout = 10

    def __init__(self, agent, medium):
        log.Logger.__init__(self, medium)

        self.agent = agent
        self.medium = medium

    def initiate(self):
        '''@see: L{manager.IAgentManager}'''

    def refused(self, refusal):
        '''@see: L{manager.IAgentManager}'''

    def bid(self, bid):
        '''@see: L{manager.IAgentManager}'''

    def closed(self):
        '''@see: L{manager.IAgentManager}'''

    def expired(self):
        '''@see: L{manager.IAgentManager}'''

    def cancelled(self, grant, cancellation):
        '''@see: L{manager.IAgentManager}'''

    def completed(self, grant, report):
        '''@see: L{manager.IAgentManager}'''

    def aborted(self, grant):
        '''@see: L{manager.IAgentManager}'''
