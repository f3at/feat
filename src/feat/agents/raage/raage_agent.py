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

from feat.agents.base import (agent, contractor, manager, partners,
                              message, replay, )
from feat.agents.common import rpc, shard, monitor, export
from feat.common import fiber, serialization
from feat.interface.contracts import ContractState
from feat.interface.protocols import InterestType


@serialization.register
class ShardPartner(agent.BasePartner):

    type_name = 'raage->shard'


class Partners(agent.Partners):

    partners.has_one('shard', 'shard_agent', ShardPartner)


@agent.register('raage_agent')
class ResourcesAllocationAgent(agent.BaseAgent):

    partners_class = Partners

    restart_strategy = monitor.RestartStrategy.local

    migratability = export.Migratability.locally

    @replay.mutable
    def initiate(self, state):
        state.medium.register_interest(
            contractor.Service(AllocationContractor))
        state.medium.register_interest(AllocationContractor)

    def startup(self):
        self.startup_monitoring()

    @replay.immutable
    def get_list_of_hosts_in_shard(self, state):
        return shard.get_host_list(self)

    @replay.journaled
    def get_neighbours(self, state):
        return shard.query_structure(self, 'raage_agent', distance=1)


class EmptyBids(Exception):
    pass


class AllocationContractor(contractor.NestingContractor):

    protocol_id = 'request-allocation'
    interest_type = InterestType.private

    @replay.entry_point
    def announced(self, state, announcement):
        f = fiber.Fiber()
        f.add_callback(fiber.drop_param,
                       self._ask_own_shard, announcement)
        f.add_callback(self._pick_best_bid)
        f.add_errback(self._nest_to_neighbours, announcement)
        f.add_callback(self._refuse_or_handover)
        f.add_both(fiber.drop_param, self.terminate_nested_manager)
        return f.succeed()

    @replay.mutable
    def _ask_own_shard(self, state, announcement):
        f = state.agent.get_list_of_hosts_in_shard()
        f.add_callback(self._start_manager, announcement.duplicate())
        return f

    @replay.mutable
    def _nest_to_neighbours(self, state, fail, announcement):
        fail.trap(EmptyBids)
        f = state.agent.get_neighbours()
        f.add_callback(self.fetch_nested_bids, announcement)
        f.add_callback(self._pick_best_bid)
        return f

    @replay.mutable
    def _start_manager(self, state, recp, announcement):
        state.host_manager = state.agent.initiate_protocol(
            HostAllocationManager, recp, announcement)
        return state.host_manager.wait_for_bids()

    @replay.immutable
    def _pick_best_bid(self, state, bids):
        if bids is None or len(bids) == 0:
            return fiber.fail(EmptyBids(
                'Resource allocation will fail as no suitable bids have been '
                'received.'))
        ret = message.Bid.pick_best(bids)[0]
        return ret

    @replay.journaled
    def _refuse_or_handover(self, state, bid):
        if bid is None:
            refusal = message.Refusal()
            state.medium.refuse(refusal)
            return
        else:
            state.host_manager.elect(bid)
            state.host_manager.terminate()
            self.handover(bid)


class HostAllocationManager(manager.BaseManager):
    '''
    Send contracts to host agents in the shard, requesting for resources
    allocation
    '''

    protocol_id = 'allocate-resources'
    announce_timeout = 2

    @replay.mutable
    def initiate(self, state, announcement):
        state.medium.announce(announcement)

    @replay.immutable
    def wait_for_bids(self, state):
        f = fiber.succeed()
        f.add_callback(fiber.drop_param,
                       state.medium.wait_for_state,
                       ContractState.closed, ContractState.expired)
        f.add_callback(lambda _: state.medium.get_bids())
        return f

    @replay.immutable
    def elect(self, state, bid):
        state.medium.elect(bid)

    @replay.journaled
    def terminate(self, state):
        state.medium.terminate()
