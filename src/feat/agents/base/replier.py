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
from zope.interface import implements

from feat.agents.base import replay, protocols
from feat.agencies import message
from feat.common import reflect, serialization, fiber
from feat.agents.application import feat

from feat.interface.protocols import *
from feat.interface.replier import *


class MetaReplier(type(replay.Replayable)):
    implements(IReplierFactory)

    def __init__(cls, name, bases, dct):
        cls.type_name = reflect.canonical_name(cls)
        cls.application.register_restorator(cls)
        super(MetaReplier, cls).__init__(name, bases, dct)


class BaseReplier(protocols.BaseInterested):

    __metaclass__ = MetaReplier

    implements(IAgentReplier)

    initiator = message.RequestMessage
    interest_type = InterestType.private

    application = feat

    protocol_type = "Request"
    protocol_id = None

    def requested(self, request):
        '''@see: L{replier.IAgentReplier}'''


class PartnershipProtocol(BaseReplier):

    protocol_id = 'partner-notification'

    @replay.journaled
    def requested(self, state, request):
        not_type = request.payload['type']
        blackbox = request.payload['blackbox']
        origin = request.payload['origin']
        sender = request.reply_to

        f = fiber.succeed(origin)
        f.add_callback(state.agent.partner_sent_notification, not_type,
                       blackbox, sender)
        f.add_both(self._send_reply)
        return f

    @replay.immutable
    def _send_reply(self, state, result):
        msg = message.ResponseMessage(payload={"result": result})
        state.medium.reply(msg)


class ProposalReceiver(BaseReplier):

    protocol_id = 'lets-pair-up'

    @replay.journaled
    def requested(self, state, request):
        f = fiber.Fiber()
        f.add_callback(state.agent.create_partner, request.reply_to,
                       role=request.payload['role'],
                       allocation_id=request.payload['allocation_id'],
                       options=request.payload['options'])
        f.add_callback(fiber.drop_param, self._send_ok)
        f.add_errback(self._send_failed)
        return f.succeed(request.payload['partner_class'])

    @replay.journaled
    def _send_ok(self, state):
        default_role = getattr(state.agent.partners_class, 'default_role',
                               None)
        payload = {'ok': True,
                   'desc': type(state.agent).identity_for_partners,
                   'default_role': default_role}
        self._reply(payload)

    @replay.journaled
    def _send_failed(self, state, failure):
        payload = {'ok': False,
                   'fail': failure}
        self._reply(payload)

    @replay.immutable
    def _reply(self, state, payload):
        msg = message.ResponseMessage(payload=payload)
        state.medium.reply(msg)


class Ping(BaseReplier):

    protocol_id = 'ping'

    @replay.entry_point
    def requested(self, state, request):
        state.medium.reply(message.ResponseMessage())
