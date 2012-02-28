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
from feat.common.text_helper import format_block
from feat.common import defer
from feat.agents.base import agent, descriptor, manager, contractor, replay
from feat.agencies import recipient
from feat.agents.application import feat


class Interest(contractor.BaseContractor):

    protocol_id = 'spam'


class Initiator(manager.BaseManager):

    protocol_id = 'spam'


@feat.register_descriptor('discoverer-agent')
class Descriptor(descriptor.Descriptor):
    pass


@feat.register_agent('discoverer-agent')
class Agent(agent.BaseAgent):

    @replay.journaled
    def initiate(self, state):
        state.medium.register_interest(contractor.Service(Interest))

    def discover(self):
        return self.discover_service(Initiator)


@common.attr(timescale=0.1)
class ServiceDiscoverySimulation(common.SimulationTest):

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        agency = spawn_agency()
        agency.start_agent(descriptor_factory('discoverer-agent'))
        agent1 = _.get_agent()
        agency.start_agent(descriptor_factory('discoverer-agent'))
        agent2 = _.get_agent()
        agency.start_agent(descriptor_factory('discoverer-agent'))

        agent3 = _.get_agent()
        """)
        yield self.process(setup)
        yield self.wait_for_idle(10)

        self.agents = list()
        self.agents.append(self.get_local('agent1'))
        self.agents.append(self.get_local('agent2'))
        self.agents.append(self.get_local('agent3'))

    @defer.inlineCallbacks
    def test_service_discovery(self):
        servicies = yield self.agents[0].discover()
        dest = map(lambda x: recipient.IRecipient(x), self.agents)
        self.assertIsInstance(servicies, list)
        self.assertEqual(3, len(servicies))
        for recp in servicies:
            self.assertTrue(recipient.IRecipient.providedBy(recp))
            self.assertTrue(recp in dest)
