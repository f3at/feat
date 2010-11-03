from zope.interface import implements, classProvides
from feat.interface import replier
from feat.common import log

 
class BaseReplier(log.Logger):
    classProvides(replier.IReplierFactory)
    implements(replier.IAgentReplier)

    log_category = "replier"
    protocol_type = "Request"
    protocol_id = None

    def __init__(self, agent, medium):
        log.Logger.__init__(self, medium)
        
        self.agent = agent
        self.medium = medium

    def requested(self, request):
        pass

