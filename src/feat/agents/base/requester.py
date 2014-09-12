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
from twisted.python.failure import Failure
from zope.interface import implements

from feat.agents.base import replay, protocols
from feat.agencies import message, recipient
from feat.common import reflect, serialization, fiber
from feat.agents.application import feat

from feat.interface.protocols import *
from feat.interface.requester import *


def say_goodbye(agent, recp, payload=None):
    origin = agent.get_own_address()
    return notify_partner(agent, recp, 'goodbye', origin, payload,
                          consume_error=True)


def notify_died(agent, recp, origin, payload=None):
    return notify_partner(agent, recp, 'died', origin, payload)


def notify_restarted(agent, recp, origin, new_address):
    return notify_partner(agent, recp, 'restarted', origin, new_address)


def notify_buried(agent, recp, origin, payload=None):
    return notify_partner(agent, recp, 'buried', origin, payload)


def ping(agent, recp):
    f = fiber.succeed(Ping)
    f.add_callback(agent.initiate_protocol, recp)
    f.add_callback(Ping.notify_finish)
    return f


def notify_partner(agent, recp, notification_type, origin, payload,
                   consume_error=False):

    req = agent.initiate_protocol(PartnershipProtocol, recp,
                                  notification_type, origin, payload)
    f = req.notify_finish()
    if consume_error:
        f.add_errback(Failure.trap, ProtocolFailed)
    return f


### Private ###


class MetaRequester(type(replay.Replayable)):
    implements(IRequesterFactory)

    def __init__(cls, name, bases, dct):
        cls.type_name = reflect.canonical_name(cls)
        cls.application.register_restorator(cls)
        super(MetaRequester, cls).__init__(name, bases, dct)


class BaseRequester(protocols.BaseInitiator):

    __metaclass__ = MetaRequester

    implements(IAgentRequester)

    protocol_type = "Request"

    application = feat

    timeout = 0

    def got_reply(self, reply):
        '''@see: L{IAgentRequester}'''

    def closed(self):
        '''@see: L{IAgentRequester}'''


class Ping(BaseRequester):

    timeout = 1
    protocol_id = 'ping'

    @replay.entry_point
    def initiate(self, state):
        msg = message.RequestMessage()
        state.medium.request(msg)


class PartnershipProtocol(BaseRequester):

    timeout = 5
    protocol_id = 'partner-notification'

    known_types = ['goodbye', 'died', 'restarted', 'buried']

    @replay.entry_point
    def initiate(self, state, notification_type, origin, blackbox=None):
        origin = recipient.IRecipient(origin)
        if notification_type not in type(self).known_types:
            raise AttributeError(
                'Expected notification type to be in %r, got %r' %\
                (type(self).known_types, notification_type, ))
        payload = {
            'type': notification_type,
            'blackbox': blackbox,
            'origin': origin}
        msg = message.RequestMessage(payload=payload)
        state.medium.request(msg)

    @replay.journaled
    def got_reply(self, state, reply):
        result = reply.payload["result"]
        if isinstance(result, Failure):
            error.handle_failure(self, result, "Error processing")
        return result

    @replay.journaled
    def closed(self, state):
        self.log('Notification expired')


class Propose(BaseRequester):

    timeout = 6
    protocol_id = 'lets-pair-up'

    @replay.entry_point
    def initiate(self, state, our_alloc_id=None, partner_alloc_id=None,
                 partner_role=None, our_role=None, substitute=None,
                 options=None):
        state.our_role = our_role
        state.allocation_id = our_alloc_id
        state.substitute = substitute
        state.options = options

        msg = message.RequestMessage(
            payload=dict(
                partner_class=type(state.agent).identity_for_partners,
                role=partner_role,
                allocation_id=partner_alloc_id,
                options=options))

        state.medium.request(msg)

    @replay.entry_point
    def got_reply(self, state, reply):
        if reply.payload['ok']:
            our_role = state.our_role or reply.payload['default_role']
            return state.agent.create_partner(
                reply.payload['desc'], reply.reply_to, state.allocation_id,
                our_role, substitute=state.substitute, options=state.options)
        else:
            self.info('Received error: %r', reply.payload['fail'])
            f = self._release_allocation()
            f.chain(fiber.fail(reply.payload['fail']))
            return f

    @replay.entry_point
    def closed(self, state):
        self.warning('Our proposal to agent %r has been ignored. How rude!',
                     state.medium.get_recipients())
        f = self._release_allocation()
        f.add_callback(fiber.override_result, None)
        return f

    @replay.mutable
    def _release_allocation(self, state):
        f = fiber.succeed()
        if state.allocation_id:
            return f.add_callback(fiber.drop_param,
                                  state.agent.release_resource,
                                  state.allocation_id)
        return f
