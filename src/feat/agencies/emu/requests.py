# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import uuid

from twisted.python import components
from zope.interface import implements

from feat.common import log
from feat.interface import recipient, requests, replier, requester, protocols
from feat.agents import message

from interface import IListener


class AgencyRequesterFactory(object):
    implements(protocols.IAgencyInitiatorFactory)

    def __init__(self, factory):
        self._factory = factory

    def __call__(self, agent, recipients, *args, **kwargs):
        return AgencyRequester(agent, recipients, *args, **kwargs)


components.registerAdapter(AgencyRequesterFactory,
                           requester.IRequesterFactory,
                           protocols.IAgencyInitiatorFactory)



class AgencyRequester(log.LogProxy, log.Logger):
    implements(requester.IAgencyRequester, IListener)

    log_category = 'agency-requester'

    def __init__(self, agent, recipients, *args, **kwargs):
        log.Logger.__init__(self, agent)
        log.LogProxy.__init__(self, agent)

        self.agent = agent
        self.recipients = recipients
        self.session_id = str(uuid.uuid1())
        self.log_name = self.session_id
        self.closed_call = None

    def initiate(self, requester):
        self.requester = requester
        if requester.timeout > 0:
            self.closed_call = self.agent.callLater(requester.timeout,
                                                    self.expired)
        requester.state = requests.RequestState.requested
        requester.initiate()

        return requester

    def expired(self):
        self.requester.closed()
        self.terminate()

    def request(self, request):
        self.debug("Sending request")
        request.session_id = self.session_id
        request.protocol_id = self.requester.protocol_id
        if self.requester.timeout > 0:
            request.expiration_time =\
                self.agent.get_time() + self.requester.timeout

        self.requester.request = self.agent.send_msg(self.recipients, request)
        
    def terminate(self):
        self.debug('Terminate called')
        self.requester.state = requests.RequestState.closed
        self.agent.unregister_listener(self.session_id)

    # IListener stuff

    def on_message(self, message):
        if self.closed_call:
            self.closed_call.cancel()
        self.requester.got_reply(message)

    def get_session_id(self):
        return self.session_id


class AgencyReplierFactory(object):
    implements(protocols.IAgencyInterestedFactory)

    def __init__(self, factory):
        self._factory = factory

    def __call__(self, agent, message):
        return AgencyReplier(agent, message)


components.registerAdapter(AgencyReplierFactory,
                           replier.IReplierFactory,
                           protocols.IAgencyInterestedFactory)


class AgencyReplier(log.LogProxy, log.Logger):
    implements(replier.IAgencyReplier, IListener)
 
    log_category = 'agency-replier'

    def __init__(self, agent, message):
        log.Logger.__init__(self, agent)
        log.LogProxy.__init__(self, agent)

        self.agent = agent
        self.request = message
        self.recipients = message.reply_to
        self.session_id = message.session_id
        self.protocol_id = message.protocol_id

        self.log_name = self.session_id
        self.message_count = 0

    def initiate(self, replier):
        self.replier = replier
        return replier
    
    def reply(self, reply):
        self.debug("Sending reply")
        reply.session_id = self.session_id
        reply.protocol_id = self.protocol_id
        reply.expiration_time = self.request.expiration_time

        self.agent.send_msg(self.recipients, reply)
        
    def terminate(self):
        self.debug('Terminate called')
        self.agent.unregister_listener(self.session_id)

    # IListener stuff

    def on_message(self, message):
        self.message_count += 1
        if self.message_count == 1:
            self.replier.requested(message)
        else:
            self.error("Got unexpected message: %r", message)

    def get_session_id(self):
        return self.session_id
