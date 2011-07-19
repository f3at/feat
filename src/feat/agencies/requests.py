# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import uuid

from twisted.python import components
from zope.interface import implements
from twisted.internet import defer

from feat.common import log, time, serialization
from feat.agents.base import message, replay
from feat.agencies import common, protocols

from interface import *
from feat.interface.serialization import *
from feat.interface.requests import *
from feat.interface.requester import *
from feat.interface.replier import *
from feat.interface.recipient import *


class AgencyRequester(log.LogProxy, log.Logger, common.StateMachineMixin,
                      common.ExpirationCallsMixin, common.AgencyMiddleMixin,
                      common.TransientInitiatorMediumBase):

    implements(ISerializable, IAgencyRequester,
               IAgencyProtocolInternal, IAgencyListenerInternal)

    type_name = "requester-medium"

    error_state = RequestState.wtf

    def __init__(self, agency_agent, factory, recipients, *args, **kwargs):
        log.Logger.__init__(self, agency_agent)
        log.LogProxy.__init__(self, agency_agent)
        common.StateMachineMixin.__init__(self)
        common.ExpirationCallsMixin.__init__(self)
        common.AgencyMiddleMixin.__init__(self)
        common.TransientInitiatorMediumBase.__init__(self)

        self.agent = agency_agent
        self.factory = factory
        self.recipients = IRecipients(recipients)
        self.expiration_time = None
        self.args = args
        self.kwargs = kwargs

    def initiate(self):
        self.agent.journal_protocol_created(self.factory, self,
                                            *self.args, **self.kwargs)
        requester = self.factory(self.agent.get_agent(), self)
        self.agent.register_protocol(self)

        self.requester = requester
        self._set_protocol_id(requester.protocol_id)

        self._set_state(RequestState.requested)
        self.expiration_time = time.future(requester.timeout)
        self._expire_at(self.expiration_time, RequestState.closed,
                        self.requester.closed)

        self.call_next(self._call, requester.initiate,
                       *self.args, **self.kwargs)

        return requester

    ### IAgencyRequester Methods ###

    @replay.named_side_effect('AgencyRequester.request')
    def request(self, request):
        request = request.clone()
        self.log("Sending request: %r.", request)
        self._ensure_state(RequestState.requested)

        if request.traversal_id is None:
            request.traversal_id = str(uuid.uuid1())

        self._send_message(request, self.expiration_time)

    @replay.named_side_effect('AgencyRequester.get_recipients')
    def get_recipients(self):
        return self.recipients

    ### IAgencyProtocolInternal Methods ###

    def get_agent_side(self):
        return self.requester

    # notify_finish() implemented in common.TransientInitiatorMediumBase

    ### IAgencyListenerInternal Methods ###

    def on_message(self, msg):
        mapping = {
            message.ResponseMessage:\
                {'state_before': RequestState.requested,
                 'state_after': RequestState.requested,
                 'method': self._on_reply}}
        self._event_handler(mapping, msg)

    ### ISerializable Methods ###

    def snapshot(self):
        return id(self)

    ### Used by ExpirationCallsMixin ###

    def _get_time(self):
        return self.agent.get_time()

    ### Required by TransientInitiatorMediumBase ###

    def call_next(self, _method, *args, **kwargs):
        return self.agent.call_next(_method, *args, **kwargs)

    ### Private Methods ###

    def _terminate(self, result):
        common.ExpirationCallsMixin._terminate(self)
        self.log("Unregistering requester")
        self.agent.unregister_protocol(self)
        common.TransientInitiatorMediumBase._terminate(self, result)
        return defer.succeed(self)

    def _on_reply(self, msg):
        d = self._call(self.requester.got_reply, msg)
        d.addCallback(self._terminate)
        return d


class AgencyReplier(log.LogProxy, log.Logger, common.StateMachineMixin,
                    common.ExpirationCallsMixin, common.AgencyMiddleMixin,
                    common.TransientInterestedMediumBase):

    implements(ISerializable, IAgencyReplier,
               IAgencyProtocolInternal, IAgencyListenerInternal)

    type_name = "replier-medium"

    error_state = RequestState.wtf

    def __init__(self, agency_agent, factory, message):
        log.Logger.__init__(self, agency_agent)
        log.LogProxy.__init__(self, agency_agent)
        common.StateMachineMixin.__init__(self)
        common.AgencyMiddleMixin.__init__(self, message.sender_id,
                                          message.protocol_id)
        common.TransientInterestedMediumBase.__init__(self)
        common.ExpirationCallsMixin.__init__(self)

        self.agent = agency_agent
        self.factory = factory
        self.request = message
        self.recipients = message.reply_to
        self._set_state(RequestState.none)

        self.message_count = 0

    def initiate(self):
        self.agent.journal_protocol_created(self.factory, self)
        replier = self.factory(self.agent.get_agent(), self)

        self.replier = replier
        self._set_state(RequestState.requested)
        return replier

    ### IAgencyReplier Methods ###

    @serialization.freeze_tag('AgencyReplier.reply')
    @replay.named_side_effect('AgencyReplier.reply')
    def reply(self, reply):
        reply = reply.clone()
        self.debug("Sending reply: %r", reply)
        self._send_message(reply, self.request.expiration_time)
        self._cancel_expiration_call()
        self._set_state(RequestState.closed)
        time.callLater(0, self._terminate, None)

    ### IAgencyProtocolInternal Methods ###

    def get_agent_side(self):
        return self.replier

    # notify_finish() implemented in common.TransientInterestedMediumBase

    ### IAgencyListenerInternal Methods ###

    def on_message(self, msg):
        mapping = {
            message.RequestMessage:\
            {'state_before': RequestState.requested,
             'state_after': RequestState.requested,
             'method': self._requested}}
        self._event_handler(mapping, msg)

    ### ISerializable Methods ###

    def snapshot(self):
        return id(self)

    ### Required by TransientInterestedMediumBase ###

    def call_next(self, _method, *args, **kwargs):
        return self.agent.call_next(_method, *args, **kwargs)

    ### Overridden Methods ###

    def _terminate(self, result):
        common.ExpirationCallsMixin._terminate(self)
        self.debug('Terminate called')
        self.agent.unregister_protocol(self)
        common.TransientInterestedMediumBase._terminate(self, result)
        return defer.succeed(self)

    ### private ###

    def _requested(self, msg):
        self._cancel_expiration_call()
        self._expire_at(msg.expiration_time, RequestState.closed,
                        self._on_expire)
        self._call(self.replier.requested, msg)

    def _on_expire(self):
        pass


class AgencyRequesterFactory(protocols.BaseInitiatorFactory):
    type_name = "requester-medium-factory"
    protocol_factory = AgencyRequester


components.registerAdapter(AgencyRequesterFactory,
                           IRequesterFactory,
                           IAgencyInitiatorFactory)


class AgencyReplierInterest(protocols.DialogInterest):
    pass


components.registerAdapter(AgencyReplierInterest,
                           IReplierFactory,
                           IAgencyInterestInternalFactory)


class AgencyReplierFactory(protocols.BaseInterestedFactory):
    type_name = "replier-medium-factory"
    protocol_factory = AgencyReplier


components.registerAdapter(AgencyReplierFactory,
                           IReplierFactory,
                           IAgencyInterestedFactory)
