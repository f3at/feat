# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.python import components
from zope.interface import implements
from twisted.internet import defer

from feat.common import log
from feat.interface import requests, replier, requester, protocols
from feat.agents.base import message

from interface import IListener, IAgencyInitiatorFactory,\
                      IAgencyInterestedFactory
from . import common


class AgencyRequesterFactory(object):
    implements(IAgencyInitiatorFactory)

    def __init__(self, factory):
        self._factory = factory

    def __call__(self, agent, recipients, *args, **kwargs):
        return AgencyRequester(agent, recipients, *args, **kwargs)


components.registerAdapter(AgencyRequesterFactory,
                           requester.IRequesterFactory,
                           IAgencyInitiatorFactory)


class AgencyRequester(log.LogProxy, log.Logger, common.StateMachineMixin,
                    common.ExpirationCallsMixin, common.AgencyMiddleMixin):
    implements(requester.IAgencyRequester, IListener)

    log_category = 'agency-requester'

    error_state = requests.RequestState.wtf

    def __init__(self, agent, recipients, *args, **kwargs):
        log.Logger.__init__(self, agent)
        log.LogProxy.__init__(self, agent)
        common.StateMachineMixin.__init__(self)
        common.ExpirationCallsMixin.__init__(self)
        common.AgencyMiddleMixin.__init__(self)

        self.agent = agent
        self.recipients = recipients
        self.expiration_time = None

        self.finish_deferred = defer.Deferred()

    def initiate(self, requester):
        self.requester = requester
        self.log_name = requester.__class__.__name__
        self._set_protocol_id(requester.protocol_id)

        self._set_state(requests.RequestState.requested)
        self.expiration_time = self.agent.get_time() + requester.timeout
        self._expire_at(self.expiration_time, self.requester.closed,
                        requests.RequestState.closed)
        self._call(requester.initiate)

        return requester

    def request(self, request):
        self.log("Sending request")
        self._ensure_state(requests.RequestState.requested)

        self.requester.request =\
            self._send_message(request, self.expiration_time)

    # private

    def _terminate(self):
        common.ExpirationCallsMixin._terminate(self)

        self.log("Unregistering requester")
        self.agent.unregister_listener(self.session_id)

        if not self.finish_deferred.called:
            self.log("Firing errback of finish_deferred")
            ex = protocols.InitiatorFailed(self.state)
            self.finish_deferred.errback(ex)

    def _on_reply(self, msg):
        self.log('on_reply')
        d = self._call(self.requester.got_reply, msg)
        d.addCallback(self.finish_deferred.callback)
        d.addCallback(lambda _: self._terminate())
        return d

    # Used by ExpirationCallsMixin

    def _get_time(self):
        return self.agent.get_time()

    # IListener stuff

    def on_message(self, msg):
        mapping = {
            message.ResponseMessage:\
                {'state_before': requests.RequestState.requested,
                 'state_after': requests.RequestState.requested,
                 'method': self._on_reply}}
        self._event_handler(mapping, msg)

    def get_session_id(self):
        return self.session_id


class AgencyReplierFactory(object):
    implements(IAgencyInterestedFactory)

    def __init__(self, factory):
        self._factory = factory

    def __call__(self, agent, message):
        return AgencyReplier(agent, message)


components.registerAdapter(AgencyReplierFactory,
                           replier.IReplierFactory,
                           IAgencyInterestedFactory)


class AgencyReplier(log.LogProxy, log.Logger, common.StateMachineMixin,
                    common.AgencyMiddleMixin):
    implements(replier.IAgencyReplier, IListener)

    log_category = 'agency-replier'

    error_state = requests.RequestState.wtf

    def __init__(self, agent, message):
        log.Logger.__init__(self, agent)
        log.LogProxy.__init__(self, agent)
        common.StateMachineMixin.__init__(self)
        common.AgencyMiddleMixin.__init__(self, message.sender_id,
                                          message.protocol_id)

        self.agent = agent
        self.request = message
        self.recipients = message.reply_to
        self._set_state(requests.RequestState.none)

        self.log_name = self.session_id
        self.message_count = 0

    def initiate(self, replier):
        self.replier = replier
        self._set_state(requests.RequestState.requested)
        return replier

    def reply(self, reply):
        self.debug("Sending reply")
        self._send_message(reply, self.request.expiration_time)
        self._terminate()

    def _terminate(self):
        self.debug('Terminate called')
        self.agent.unregister_listener(self.session_id)

    # IListener stuff

    def on_message(self, msg):
        mapping = {
            message.RequestMessage:\
            {'state_before': requests.RequestState.requested,
             'state_after': requests.RequestState.closed,
             'method': self.replier.requested}}
        self._event_handler(mapping, msg)

    def get_session_id(self):
        return self.session_id
