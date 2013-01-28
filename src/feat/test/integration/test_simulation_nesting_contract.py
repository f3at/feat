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
from feat.test.integration import common
from feat.agents.base import agent, contractor, replay, manager, descriptor
from feat.agencies import message, recipient
from feat.common import text_helper, defer, fiber

from feat.interface.protocols import ProtocolFailed
from feat.agents.application import feat


@feat.register_descriptor('contract_nesting_agent')
class Descriptor(descriptor.Descriptor):
    pass


@feat.register_agent('contract_nesting_agent')
class Agent(agent.BaseAgent):

    @replay.mutable
    def initiate(self, state, recp=None, index=None):
        state.to_nest = recp and recipient.IRecipient(recp)
        state.index = index
        state.announce = False
        state.granted = False
        state.completed = False
        state.should_fail_grant = False
        state.medium.register_interest(NestedStuff)

    @replay.immutable
    def get_to_nest(self, state):
        return state.to_nest

    @replay.mutable
    def got(self, state, what):
        setattr(state, what, True)

    @replay.immutable
    def get_from_state(self, state, what):
        return getattr(state, what)

    @replay.mutable
    def start(self, state):
        m = state.medium.initiate_protocol(NestedFunManager, state.to_nest)
        return m.notify_finish()


class NestedStuff(contractor.NestingContractor):

    protocol_id = 'test:nested_stuff'

    @replay.mutable
    def announced(self, state, announce):
        state.agent.got('announce')
        to_nest = state.agent.get_from_state('to_nest')
        f = fiber.succeed()
        if to_nest:
            f.add_callback(fiber.drop_param, self.fetch_nested_bids,
                           [to_nest], announce)
        f.add_callback(self._send_bid)
        return f

    @replay.mutable
    def _send_bid(self, state, nested):
        state.medium.bid(message.Bid())

    @replay.mutable
    def granted(self, state, grant):
        self.grant_nested_bids(grant)
        state.agent.got('granted')
        f = self.wait_for_nested_complete()
        f.add_callback(fiber.drop_param, self._finalize)
        return f

    @replay.journaled
    def _finalize(self, state):
        if not state.agent.get_from_state('should_fail_grant'):
            state.agent.got('completed')
            state.medium.complete(message.FinalReport())


class NestedFunManager(manager.BaseManager):

    protocol_id = 'test:nested_stuff'

    @replay.entry_point
    def initiate(self, state):
        state.medium.announce(message.Announcement())

    @replay.entry_point
    def closed(self, state):
        bid = state.medium.get_bids()[0]
        state.medium.grant((bid, message.Grant()))


@common.attr(timescale=0.05)
class TestNesting(common.SimulationTest):

    def prolog(self):
        setup = text_helper.format_block("""
        agency = spawn_agency()
        desc1 = descriptor_factory('contract_nesting_agent')
        desc2 = descriptor_factory('contract_nesting_agent')
        desc3 = descriptor_factory('contract_nesting_agent')
        desc4 = descriptor_factory('contract_nesting_agent')

        agent1 = agency.start_agent(desc1, recp=desc2, index=1)
        agency.start_agent(desc2, recp=desc3, index=2)
        agency.start_agent(desc3, recp=desc4, index=3)
        agent4 = agency.start_agent(desc4, index=4)
        wait_for_idle()
        """)
        return self.process(setup)

    @defer.inlineCallbacks
    def testItWorks(self):
        self.assertEqual(4, self.count_agents('contract_nesting_agent'))
        agent1 = self.get_local('agent1').get_agent()
        yield agent1.start()
        for medium in self.driver.iter_agents('contract_nesting_agent'):
            agent = medium.get_agent()
            index = agent.get_from_state('index')
            if index == 1:
                # first agent is the one initiating, he doesnt have contractor
                # running
                continue
            self.assertTrue(agent.get_from_state('announce'))
            self.assertTrue(agent.get_from_state('granted'))
            self.assertTrue(agent.get_from_state('completed'))

    @defer.inlineCallbacks
    def testLastFailsGranted(self):
        agent4 = self.get_local('agent4').get_agent()
        agent1 = self.get_local('agent1').get_agent()
        agent4.got('should_fail_grant')
        d = agent1.start()
        self.assertFailure(d, ProtocolFailed)
        yield d

        for medium in self.driver.iter_agents('contract_nesting_agent'):
            agent = medium.get_agent()
            index = agent.get_from_state('index')
            if index == 1:
                # first agent is the one initiating, he doesnt have contractor
                # running
                continue
            self.assertTrue(agent.get_from_state('announce'))
            self.assertTrue(agent.get_from_state('granted'))
            self.assertFalse(agent.get_from_state('completed'))
