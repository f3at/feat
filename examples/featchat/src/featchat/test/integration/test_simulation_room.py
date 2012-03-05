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
from feat.common import defer, text_helper, first
from feat.agents.common import host
from featchat.application import featchat


featchat.load()


@common.attr(timescale=0.1)
class RoomSimulation(common.SimulationTest):

    def setUp(self):
        # override the configuration of connection agent
        # we do this here only to demonstrate this is possibility
        # keep in mind that it needs to be done before the setUp of
        # SimulationTest, which creates the simulation driver.
        from featchat.agents.connection import connection_agent
        config = connection_agent.ConnectionAgentConfiguration(
            doc_id = 'test-connection-config',
            connections_limit = 2)
        featchat.initial_data(config)
        self.override_config('connection_agent', config)

        return common.SimulationTest.setUp(self)

    @defer.inlineCallbacks
    def prolog(self):
        # Define a host definition object to pass to initialization of host
        # agent. Connections Agent requires a chat port resource to start.
        hostdef = host.HostDef(ports_ranges=dict(chat=(5000, 5010)))
        # assign it to local variable in the context of scripting language
        self.set_local('hostdef', hostdef)

        setup = text_helper.format_block("""
        agency = spawn_agency()
        agency.disable_protocol('setup-monitoring', 'Task')
        agency.start_agent(descriptor_factory('host_agent'), hostdef=hostdef)
        host = _.get_agent()
        wait_for_idle()

        host.start_agent(descriptor_factory('room_agent'))
        """)

        yield self.process(setup)
        self.assertEqual(1, self.count_agents('room_agent'))
        self.room = first(self.driver.iter_agents('room_agent')).get_agent()

    @defer.inlineCallbacks
    def testJoinCreatesConnectionAgents(self):
        self.assertEqual(0, self.count_agents('connection_agent'))
        # join to the room, this should create connection_agent
        res = yield self.room.generate_join_url()
        self.assertTrue('session_id' in res)
        self.assertTrue('url' in res)
        self.assertEqual(1, self.count_agents('connection_agent'))

        # get the list for the room
        llist = yield self.room.get_list()
        self.assertTrue(res['session_id'] in llist)

        # check state of connection agent
        connection = first(
            self.driver.iter_agents('connection_agent')).get_agent()
        pc = connection.get_pending_connections()
        self.assertTrue(res['session_id'] in pc)

        # now wait for this connection attempt to expire
        yield common.delay(None, 11)
        pc = connection.get_pending_connections()
        self.assertFalse(res['session_id'] in pc)

        # now do the same 3 times do check that another agent is spawned
        for x in range(3):
            res = yield self.room.generate_join_url()
            self.assertTrue('session_id' in res)
            self.assertTrue('url' in res)
        self.assertEqual(2, self.count_agents('connection_agent'))

        # get the list for the room
        llist = yield self.room.get_list()
        self.assertEqual(3, len(llist))

        # now wait for all connections attempts to expire, get the list
        # which should be empty and assert that we are down to single
        # connection agent
        yield common.delay(None, 11)
        llist = yield self.room.get_list()
        yield self.wait_for_idle(10)
        self.assertEqual(0, len(llist))
        self.assertEqual(1, self.count_agents('connection_agent'))
