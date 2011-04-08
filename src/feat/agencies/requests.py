# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import uuid

from twisted.python import components
from zope.interface import implements
from twisted.internet import defer

from feat.common import log, delay, serialization
from feat.interface import requests, replier, requester, protocols
from feat.agents.base import message, replay

from interface import IListener, IAgencyInitiatorFactory,\
                      IAgencyInterestedFactory
from feat.agencies import common


class AgencyRequesterFactory(object):
    implements(IAgencyInitiatorFactory, serialization.ISerializable)

    type_name = "requester-medium-factory"

    def __init__(self, factory):
        self._factory = factory

    def __call__(self, agent, recipients, *args, **kwargs):
        return AgencyRequester(agent, recipients, *args, **kwargs)

    # ISerializable

    def snapshot(self):
        return None


components.registerAdapter(AgencyRequesterFactory,
                           requester.IRequesterFactory,
                           IAgencyInitiatorFactory)


class AgencyRequester(log.LogProxy, log.Logger, common.StateMachineMixin,
                    common.ExpirationCallsMixin, common.AgencyMiddleMixin,
                      common.InitiatorMediumBase):
    implements(requester.IAgencyRequester, IListener,
               serialization.ISerializable)

    log_category = "requester-medium"
    type_name = "requester-medium"

    error_state = requests.RequestState.wtf

    def __init__(self, agent, recipients, *args, **kwargs):
        log.Logger.__init__(self, agent)
        log.LogProxy.__init__(self, agent)
        common.StateMachineMixin.__init__(self)
        common.ExpirationCallsMixin.__init__(self)
        common.AgencyMiddleMixin.__init__(self)
        common.InitiatorMediumBase.__init__(self)

        self.agent = agent
        self.recipients = recipients
        self.expiration_time = None
        self.args = args
        self.kwargs = kwargs

    def initiate(self, requester):
        self.requester = requester
        self.log_name = requester.__class__.__name__
        self._set_protocol_id(requester.protocol_id)

        self._set_state(requests.RequestState.requested)
        self.expiration_time = self.agent.get_time() + requester.timeout
        self._expire_at(self.expiration_time, self.requester.closed,
                        requests.RequestState.closed)

        self.agent.call_next(self._call, requester.initiate,
                             *self.args, **self.kwargs)

        return requester

    @replay.named_side_effect('AgencyRequester.request')
    def request(self, request):
        request = request.clone()
        self.log("Sending request: %r.", request)
        self._ensure_state(requests.RequestState.requested)

        if request.traversal_id is None:
            request.traversal_id = str(uuid.uuid1())

        self._send_message(request, self.expiration_time)

    # private

    def _terminate(self, arg):
        common.ExpirationCallsMixin._terminate(self)
        self.log("Unregistering requester")
        self.agent.unregister_listener(self.session_id)
        common.InitiatorMediumBase._terminate(self, arg)

    def _on_reply(self, msg):
        self.log('on_reply')
        d = self._call(self.requester.got_reply, msg)
        d.addCallback(self._terminate)
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

    def get_agent_side(self):
        return self.requester

    # ISerializable

    def snapshot(self):
        return id(self)


class AgencyReplierFactory(object):
    implements(IAgencyInterestedFactory, serialization.ISerializable)

    type_name = "replier-medium-factory"

    def __init__(self, factory):
        self._factory = factory

    def __call__(self, agent, message):
        return AgencyReplier(agent, message)

    # ISerializable

    def snapshot(self):
        return None


components.registerAdapter(AgencyReplierFactory,
                           replier.IReplierFactory,
                           IAgencyInterestedFactory)


class AgencyReplier(log.LogProxy, log.Logger, common.StateMachineMixin,
                    common.AgencyMiddleMixin, common.InterestedMediumBase):

    implements(replier.IAgencyReplier, IListener,
               serialization.ISerializable)

    log_category = "replier-medium"
    type_name = "replier-medium"

    error_state = requests.RequestState.wtf

    def __init__(self, agent, message):
        log.Logger.__init__(self, agent)
        log.LogProxy.__init__(self, agent)
        common.StateMachineMixin.__init__(self)
        common.AgencyMiddleMixin.__init__(self, message.sender_id,
                                          message.protocol_id)
        common.InterestedMediumBase.__init__(self)

        self.agent = agent
        self.request = message
        self.recipients = message.reply_to
        self._set_state(requests.RequestState.none)

        self.message_count = 0

    def initiate(self, replier):
        self.replier = replier
        self.log_name = replier.__class__.__name__
        self._set_state(requests.RequestState.requested)
        return replier

    @serialization.freeze_tag('AgencyReplier.reply')
    @replay.named_side_effect('AgencyReplier.reply')
    def reply(self, reply):
        reply = reply.clone()
        self.debug("Sending reply: %r", reply)
        self._send_message(reply, self.request.expiration_time)
        delay.callLater(0, self._terminate, None)

    def _terminate(self, arg):
        self.debug('Terminate called')
        self.agent.unregister_listener(self.session_id)
        common.InterestedMediumBase._terminate(self, arg)

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

    def get_agent_side(self):
        return self.replier

    # ISerializable

    def snapshot(self):
        return id(self)
