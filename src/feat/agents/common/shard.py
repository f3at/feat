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
import uuid

from zope.interface import Interface

from feat.agents.base import replay, descriptor, manager, collector
from feat.agencies import message, recipient
from feat.common import fiber
from feat.agents.application import feat

from feat.interface.protocols import *


__all__ = ['start_manager', 'query_structure', 'get_host_list']


class IShardNotificationHandler(Interface):

    def on_new_neighbour_shard(recipient):
        """Called when we got a new neighbour shard."""

    def on_neighbour_shard_gone(recipient):
        """Called when neighbour shard goes away."""


def start_manager(agent):
    f = agent.discover_service(JoinShardManager, timeout=1)
    f.add_callback(lambda recp:
                   agent.initiate_protocol(JoinShardManager, recp))
    f.add_callback(JoinShardManager.notify_finish)
    return f


def query_structure(agent, partner_type, shard_recip=None, distance=1):
    if shard_recip is None:
        shard_recip = agent.query_partners('shard')
    if not shard_recip:
        agent.warning(
            "query_structure() called, but agent doesn't have shard partner, "
            "hence none to send a query to.")
        return fiber.succeed([])
    else:
        return agent.call_remote(shard_recip, 'query_structure',
                                 partner_type, distance, _timeout=10)


def get_host_list(agent):
    shard_recp = agent.query_partners('shard')
    if not shard_recp:
        agent.warning(
            "get_host_list() called, but agent doesn't have shard partner, "
            "returning empty list")
        return fiber.succeed(list())
    else:
        return agent.call_remote(shard_recp, 'get_host_list', _timeout=1)


def register_for_notifications(agent):
    shard = agent.get_shard_id()
    recip = recipient.Broadcast(ShardNotificationCollector.protocol_id, shard)
    return agent.register_interest(ShardNotificationCollector)


class JoinShardManager(manager.BaseManager):

    protocol_id = 'join-shard'
    announce_timeout = 4

    @replay.immutable
    def initiate(self, state):
        msg = message.Announcement()
        msg.payload['joining_agent'] = state.agent.get_own_address()
        state.medium.announce(msg)

    @replay.immutable
    def closed(self, state):
        bids = state.medium.get_bids()
        best_bid = message.Bid.pick_best(bids)[0]
        msg = message.Grant()
        msg.payload['joining_agent'] = state.agent.get_own_address()
        params = (best_bid, msg)
        state.medium.grant(params)

    @replay.mutable
    def completed(self, state, reports):
        pass


@replay.side_effect
def generate_shard_value():
    return unicode(uuid.uuid1())


@feat.register_descriptor("shard_agent")
class Descriptor(descriptor.Descriptor):
    pass


def prepare_descriptor(agent, shard=None):
    shard = shard or generate_shard_value()
    desc = Descriptor(shard=shard)
    return agent.save_document(desc)


class ShardNotificationCollector(collector.BaseCollector):

    protocol_id = 'shard-notification'
    interest_type = InterestType.public

    @replay.mutable
    def initiate(self, state):
        # Just in case there is an adapter involved
        state.handler = IShardNotificationHandler(state.agent)

    @replay.immutable
    def notified(self, state, msg):
        name, args = msg.payload
        handler = getattr(self, "on_" + name, None)
        if not handler:
            self.warning("Unknown shard notification: %s", name)
            return
        return handler(*args)

    @replay.immutable
    def on_new_neighbour(self, state, recipient):
        return state.handler.on_new_neighbour_shard(recipient)

    @replay.immutable
    def on_neighbour_gone(self, state, recipient):
        return state.handler.on_neighbour_shard_gone(recipient)
