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
from feat.agents.common import host, rpc
from feat.agents.base import agent

from feat.interface.agent import Address

from featchat.application import featchat


featchat.load()


class DummyRoomAgent(agent.BaseAgent):

    @rpc.publish
    def get_list(self):
        res = {'session1': u'some.ip', 'session2': u'other.ip'}
        return res

    @rpc.publish
    def generate_join_url(self):
        res = {'url': u'20.30.10.30:1003', 'session_id': u'sth'}
        return res


class ApiTest(common.SimulationTest):

    def setUp(self):
        self.override_agent('room_agent', DummyRoomAgent, application=featchat)
        return common.SimulationTest.setUp(self)

    @defer.inlineCallbacks
    def prolog(self):
        hostdef = host.HostDef(categories=dict(address=Address.fixed),
                               ports_ranges=dict(dns=(8000, 8000)))
        self.set_local('hostdef', hostdef)

        setup = text_helper.format_block("""
        a = spawn_agency()
        a.disable_protocol('setup-monitoring', 'Task')
        medium = a.start_agent(descriptor_factory('host_agent'),\
                               hostdef=hostdef)
        host = medium.get_agent()
        wait_for_idle()
        """)

        dns = text_helper.format_block("""
        host.start_agent(descriptor_factory('dns_agent'))
        """)

        api = text_helper.format_block("""
        host.start_agent(descriptor_factory('api_agent'))
        wait_for_idle()
        """)

        yield self.process(setup)
        yield self.process(dns)
        yield self.process(api)
        self.dns = first(self.driver.iter_agents('dns_agent')).get_agent()
        self.api = first(self.driver.iter_agents('api_agent')).get_agent()

    @common.attr(timescale=0.1)
    @defer.inlineCallbacks
    def testStartJoinRoomAndQuery(self):
        self.assertEqual(1, self.count_agents('dns_agent'))
        self.assertEqual(1, self.count_agents('api_agent'))
        # check that we got properly registered to dns
        suffix = self.dns.get_suffix()
        exp = "api.%s" % (suffix, )

        address = yield self.dns.lookup_address(exp, '127.0.0.1')
        self.assertEqual(1, len(address))

        # listing rooms should give empty result
        res = yield self.api.get_room_list()
        self.assertEqual([], res)

        # now join first nonexisting room
        room = 'room'
        self.assertEqual(0, self.count_agents('room_agent'))
        res = yield self.api.get_url_for_room(room)
        exp = {'url': u'20.30.10.30:1003', 'session_id': u'sth'}
        self.assertEqual(exp, res)
        # room agent should get created
        self.assertEqual(1, self.count_agents('room_agent'))

        #second query should not change anything
        res = yield self.api.get_url_for_room(room)
        exp = {'url': u'20.30.10.30:1003', 'session_id': u'sth'}
        self.assertEqual(exp, res)
        self.assertEqual(1, self.count_agents('room_agent'))

        # listing rooms should give single result
        res = yield self.api.get_room_list()
        self.assertEqual([room], res)

        # now get the list for existing room
        res = yield self.api.get_list_for_room(room)
        exp = {'session1': u'some.ip', 'session2': u'other.ip'}
        self.assertEqual(exp, res)

        # and list for nonexising one
        d = self.api.get_list_for_room('nonexisitng room')
        self.assertFailure(d, ValueError)
        yield d

        # create another room
        room = 'room2'
        res = yield self.api.get_url_for_room(room)
        exp = {'url': u'20.30.10.30:1003', 'session_id': u'sth'}
        self.assertEqual(exp, res)
        # room agent should get created
        self.assertEqual(2, self.count_agents('room_agent'))

        # check that after terminating we get deregistered from DNS
        self.api.terminate()
        yield self.wait_for_idle(10)
        exp = "api.%s" % (suffix, )
        address = yield self.dns.lookup_address(exp, '127.0.0.1')
        self.assertEqual(0, len(address))
