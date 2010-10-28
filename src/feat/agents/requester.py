from feat.agents import message
from zope.interface import implements
from feat.interface import requester
from feat.common import log

import uuid

class BaseRequester(log.Logger):
    implements(requester.IAgentRequester)
    
    log_category = "base_requester"

    def __init__(self, agent, medium, recipients):
        log.Logger.__init__(self, medium)

        self.agent = agent
        self.medium = medium
        self.recipients = recipients    

        self.protocol_key = None
        self.protocol_type = "Request"

    def initiate(self):
        self.debug("Initiate called")
        msg = message.RequestMessage()
        msg.message_id = uuid.uuid1()
        msg.protocol_id = str(self.__class__)
        return msg

    def got_reply(reply):
        pass
