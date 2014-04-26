# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import uuid

from zope.interface import implements

from feat.common import time, serialization, adapter
from feat.agents.base import replay
from feat.agencies import common, protocols, message

from feat.agencies.interface import IAgencyListenerInternal
from feat.agencies.interface import IAgencyInitiatorFactory
from feat.agencies.interface import IAgencyInterestedFactory
from feat.agencies.interface import IAgencyInterestInternalFactory
from feat.interface.serialization import ISerializable
from feat.interface.requests import RequestState
from feat.interface.requester import IAgencyRequester, IRequesterFactory
from feat.interface.replier import IAgencyReplier, IReplierFactory
from feat.interface.recipient import IRecipients


class AgencyRequester(common.AgencyMiddleBase):

    implements(ISerializable, IAgencyRequester, IAgencyListenerInternal)

    type_name = "requester-medium"

    error_state = RequestState.wtf

    def __init__(self, agency_agent, factory, recipients, *args, **kwargs):
        common.AgencyMiddleBase.__init__(self, agency_agent, factory)

        self.recipients = IRecipients(recipients)
        self.args = args
        self.kwargs = kwargs

    def initiate(self):
        requester = self.factory(self.agent.get_agent(), self)

        self.requester = requester
        self.set_protocol_id(requester.protocol_id)

        self._set_state(RequestState.requested)
        self.expiration_time = time.future(requester.timeout)
        self.set_timeout(self.expiration_time, RequestState.closed,
                         self._run_and_terminate, self.requester.closed)

        self.call_agent_side(requester.initiate, *self.args,
                             ensure_state=RequestState.requested,
                             **self.kwargs)

        return requester

    ### IAgencyRequester Methods ###

    @replay.named_side_effect('AgencyRequester.request')
    def request(self, request):
        request = request.duplicate()
        self.log("Sending request: %r.", request)
        if not self._ensure_state(RequestState.requested):
            return

        if request.traversal_id is None:
            request.traversal_id = str(uuid.uuid1())

        self.send_message(request, self.expiration_time)

    @replay.named_side_effect('AgencyRequester.get_recipients')
    def get_recipients(self):
        return self.recipients

    ### IAgencyProtocolInternal Methods ###

    def get_agent_side(self):
        return self.requester

    ### IAgencyListenerInternal Methods ###

    def on_message(self, msg):
        mapping = {
            message.ResponseMessage:\
                {'state_before': RequestState.requested,
                 'state_after': RequestState.requested,
                 'method': self._on_reply}}
        handler = self._event_handler(mapping, msg)
        if callable(handler):
            return handler(msg)

    ### ISerializable Methods ###

    def snapshot(self):
        return id(self)

    ### Private Methods ###

    def _on_reply(self, msg):
        self.cancel_timeout()
        d = self.call_agent_side(self.requester.got_reply, msg,
                                 ensure_state=RequestState.requested)
        d.addCallback(self.finalize)
        return d


class AgencyReplier(common.AgencyMiddleBase):

    implements(ISerializable, IAgencyReplier, IAgencyListenerInternal)

    type_name = "replier-medium"

    error_state = RequestState.wtf

    def __init__(self, agency_agent, factory, message):
        common.AgencyMiddleBase.__init__(self, agency_agent, factory,
                                         remote_id=message.sender_id,
                                         protocol_id=message.protocol_id)
        self.request = message
        self.recipients = message.reply_to
        self._set_state(RequestState.none)

    def initiate(self):
        replier = self.factory(self.agent.get_agent(), self)
        self.replier = replier
        self._set_state(RequestState.requested)
        return replier

    ### IAgencyReplier Methods ###

    @serialization.freeze_tag('AgencyReplier.reply')
    @replay.named_side_effect('AgencyReplier.reply')
    def reply(self, reply):
        reply = reply.duplicate()
        self.debug("Sending reply: %r", reply)
        self.send_message(reply, self.request.expiration_time)
        self.cancel_timeout()
        self._set_state(RequestState.closed)
        self.finalize(None)

    ### IAgencyProtocolInternal Methods ###

    def get_agent_side(self):
        return self.replier

    ### IAgencyListenerInternal Methods ###

    def on_message(self, msg):
        mapping = {
            message.RequestMessage:\
            {'state_before': RequestState.requested,
             'state_after': RequestState.requested,
             'method': self._requested}}
        handler = self._event_handler(mapping, msg)
        if callable(handler):
            handler(msg)

    ### ISerializable Methods ###

    def snapshot(self):
        return id(self)

    ### Required by TransientInterestedMediumBase ###

    def call_next(self, _method, *args, **kwargs):
        return self.agent.call_next(_method, *args, **kwargs)

    ### private ###

    def _requested(self, msg):
        self.set_timeout(msg.expiration_time, RequestState.closed,
                         self.finalize, None)
        self.call_agent_side(self.replier.requested, msg,
                             ensure_state=RequestState.requested)


@adapter.register(IRequesterFactory, IAgencyInitiatorFactory)
class AgencyRequesterFactory(protocols.BaseInitiatorFactory):
    type_name = "requester-medium-factory"
    protocol_factory = AgencyRequester


@adapter.register(IReplierFactory, IAgencyInterestInternalFactory)
class AgencyReplierInterest(protocols.DialogInterest):
    pass


@adapter.register(IReplierFactory, IAgencyInterestedFactory)
class AgencyReplierFactory(protocols.BaseInterestedFactory):
    type_name = "replier-medium-factory"
    protocol_factory = AgencyReplier
