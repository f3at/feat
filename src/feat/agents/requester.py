from feat.agents import message
from zope.interface import implements, classProvides
from feat.interface import requester
from feat.common import log

import uuid

class BaseRequester(log.Logger):
    classProvides(requester.IRequesterFactory)
    implements(requester.IAgentRequester)

    log_category = "requester"
    timeout = 0
    protocol_id = None

    def __init__(self, agent, medium, recipients):
        log.Logger.__init__(self, medium)

        self.agent = agent
        self.medium = medium
        self.recipients = recipients

    def initiate(self):
        pass

    def got_reply(self, reply):
        pass

    def closed(self):
        pass
        
        
