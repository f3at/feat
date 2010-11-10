from zope.interface import implements, classProvides

from feat.common import log
from feat.interface import requester, requests

from . import message


class BaseRequester(log.Logger):
    classProvides(requester.IRequesterFactory)
    implements(requester.IAgentRequester)

    log_category = "requester"
    timeout = 0
    protocol_id = None

    def __init__(self, agent, medium, *args, **kwargs):
        log.Logger.__init__(self, medium)

        self.agent = agent
        self.medium = medium

    def initiate(self):
        pass

    def got_reply(self, reply):
        pass

    def closed(self):
        pass


