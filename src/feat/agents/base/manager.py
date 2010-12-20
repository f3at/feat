from zope.interface import implements
from feat.interface import manager
from feat.common import log
from feat.agencies import agency


class Meta(type):
    implements(manager.IManagerFactory)


class BaseManager(log.Logger, agency.InitiatorMixin):
    """
    I am a base class for managers of contracts.

    @ivar protocol_type: the type of contract this manager manages.
                         Must match the type of the contractor for this
                         contract; see L{feat.agents.contractor.BaseContractor}
    @type protocol_type: str
    """
    __metaclass__ = Meta

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
        agency.InitiatorMixin.__init__(self)

    def initiate(self):
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
