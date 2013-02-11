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
from feat.agents.base import manager, replay, descriptor
from feat.agencies import message, retrying
from feat.agents.application import feat
from feat.common import error, fiber

__all__ = ['allocate_resource', 'AllocationManager', 'discover', 'Descriptor']


class AllocationFailedError(error.FeatError):

    def __init__(self, resources, *args, **kwargs):
        msg = "Could not allocate resources: %r" % resources
        error.FeatError.__init__(self, msg, *args, **kwargs)


def allocate_resource(agent, resources, shard=None,
                      categories={}, max_distance=None,
                      agent_id=None):

    f = discover(agent, shard)
    f.add_callback(fiber.inject_param, 1, agent.initiate_protocol,
        AllocationManager, resources, categories, max_distance, agent_id)
    f.add_callback(fiber.call_param, 'notify_finish')
    f.add_errback(fiber.raise_error, AllocationFailedError, resources)
    return f


def retrying_allocate_resource(agent, resources, shard=None,
                               categories={}, max_distance=None,
                               agent_id=None, max_retries=3):

    def on_error(f):
        raise AllocationFailedError(resources, cause=f)

    f = discover(agent, shard)
    factory = retrying.RetryingProtocolFactory(AllocationManager,
                                               max_retries=max_retries)
    f.add_callback(fiber.inject_param, 1, agent.initiate_protocol,
                   factory, resources, categories, max_distance, agent_id)
    f.add_callback(fiber.call_param, 'notify_finish')
    f.add_errback(fiber.raise_error, AllocationFailedError, resources)
    return f


def discover(agent, shard=None):
    shard = shard or agent.get_shard_id()
    return agent.discover_service(AllocationManager, timeout=1, shard=shard)


class AllocationManager(manager.BaseManager):

    protocol_id = 'request-allocation'
    announce_timeout = 6

    @replay.entry_point
    def initiate(self, state, resources, categories, max_distance, agent_id):
        self.log("initiate manager")
        state.resources = resources
        msg = message.Announcement()
        msg.max_distance = max_distance
        msg.payload['resources'] = state.resources
        msg.payload['categories'] = categories
        msg.payload['agent_id'] = agent_id
        state.medium.announce(msg)

    @replay.entry_point
    def closed(self, state):
        self.log("close manager")
        bids = state.medium.get_bids()
        best_bid = message.Bid.pick_best(bids)[0]
        msg = message.Grant()
        params = (best_bid, msg)
        state.medium.grant(params)

    @replay.entry_point
    def completed(self, state, reports):
        self.log("completed manager")
        report = reports[0]
        return report.payload['allocation_id'], report.reply_to


@feat.register_descriptor("raage_agent")
class Descriptor(descriptor.Descriptor):
    pass
