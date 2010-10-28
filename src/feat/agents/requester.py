from feat.agents import message
from zope.interface import implements
from feat.interface import requester

import uuid

class BaseRequester(object):
    implements(requester.IAgentRequester)
    
    def __init__(self, agent, medium, recipients):
        self.agent = agent
        self.medium = medium
        self.recipients = recipients    

        self.protocol_key = None
        self.protocol_type = "Request"

    def initiate(self):
        msg = message.RequestMessage()
        msg.message_id = uuid.uuid1()
        msg.protocol_id = str(self.__class__)
        return msg

    def got_reply(reply):
        pass
