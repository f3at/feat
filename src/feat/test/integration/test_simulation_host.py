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
import socket

from twisted.internet import defer

from feat.test.integration import common

from feat.agents.base import agent, descriptor, replay, resource
from feat.database import document
from feat.agents.common import host
from feat.common.text_helper import format_block
from feat.common import first
from feat.agents.application import feat

from feat.interface.recipient import IRecipient
from feat.interface.agent import Access, Address, Storage


@common.attr(timescale=0.05)
class HostAgentTests(common.SimulationTest):

    NUM_PORTS = 999

    def prolog(self):
        setup = format_block("""
        agency = spawn_agency(hostname='test.host.lan')
        agent = agency.get_host_agent()
        """)
        return self.process(setup)

    def testDefaultResources(self):
        agent = self.get_local('agent')
        totals = agent._get_state().resources.get_totals()
        self.assertTrue("host" in totals)
        self.assertTrue("bandwidth" in totals)
        self.assertTrue("epu" in totals)
        self.assertTrue("core" in totals)
        self.assertTrue("mem" in totals)

    def testDefaultRequeriments(self):
        agent = self.get_local('agent')
        cats = agent._get_state().categories
        self.assertTrue("access" in cats)
        self.assertTrue("storage" in cats)
        self.assertTrue("address" in cats)

    def testHostname(self):
        expected = 'test.host.lan_1'
        hostname = socket.gethostname()
        expected_ip = socket.gethostbyname(hostname)
        agent = self.get_local('agent')
        self.assertEqual(agent.get_hostname(), expected)
        self.assertEqual(agent.get_ip(), expected_ip)


@common.attr(timescale=0.1)
class HostAgentRestartTest(common.SimulationTest):

    NUM_PORTS = 999

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        agency = spawn_agency()
        agent = agency.get_host_agent()
        medium = find_agent(agent)
        """)
        yield self.process(setup)
        yield self.wait_for_idle(10)

    @defer.inlineCallbacks
    def testKillHost(self):
        self.assertEqual(1, self.count_agents('host_agent'))
        self.assertEqual(1, self.count_agents('shard_agent'))
        self.assertEqual(1, self.count_agents('raage_agent'))
        self.assertEqual(1, self.count_agents('monitor_agent'))

        yield self.wait_for_idle(10)
        medium = self.get_local('medium')
        desc = medium.get_descriptor()

        @defer.inlineCallbacks
        def has_monitor():
            p = yield medium.agent.query_partners('monitors')
            defer.returnValue(len(p) > 0)
        yield self.wait_for(has_monitor, 10)
        yield medium.terminate_hard()
        self.assertEqual(0, self.count_agents('host_agent'))
        agency = self.get_local('agency')
        self.assertEqual(1, desc.instance_id)

        yield agency.start_agent(desc)
        yield self.wait_for_idle(10)
        new_desc = yield self.driver._database_connection.get_document(
            desc.doc_id)
        self.assertEqual(2, new_desc.instance_id)
        self.assertEqual(1, self.count_agents('shard_agent'))
        self.assertEqual(1, self.count_agents('raage_agent'))
        self.assertEqual(1, self.count_agents('monitor_agent'))

        monitor = first(self.driver.iter_agents('monitor_agent')).get_agent()
        hosts = yield monitor.query_partners('hosts')
        self.assertEqual(2, hosts[0].instance_id)


@common.attr(timescale=0.05)
class HostAgentDefinitionTests(common.SimulationTest):

    def prolog(self):
        setup = format_block("""
        agency1 = spawn_agency(hostdef=hostdef)
        agent1 = agency1.get_host_agent()

        agency2 = spawn_agency(hostdef=hostdef_id)
        agent2 = agency2.get_host_agent()
        """)

        hostdef = host.HostDef()
        hostdef.doc_id = "someid"
        hostdef.resources = {"spam": 999, "bacon": 42, "eggs": 3, "epu": 10}

        self.driver.save_document(hostdef)
        self.set_local("hostdef", hostdef)
        self.set_local("hostdef_id", "someid")

        return self.process(setup)

    def testDefaultResources(self):

        def check_resources(resc):
            totals = resc.get_totals()
            self.assertTrue("spam" in totals)
            self.assertTrue("bacon" in totals)
            self.assertTrue("eggs" in totals)
            self.assertEqual(totals["spam"], 999)
            self.assertEqual(totals["bacon"], 42)
            self.assertEqual(totals["eggs"], 3)

        agent1 = self.get_local('agent1')
        check_resources(agent1._get_state().resources)

        agent2 = self.get_local('agent2')
        check_resources(agent2._get_state().resources)


@common.attr(timescale=0.05)
class HostAgentRequerimentsTest(common.SimulationTest):

    def prolog(self):
        setup = format_block("""
            agency = spawn_agency(hostdef=hostdef)
            agent = agency.get_host_agent()
            """)

        hostdef = host.HostDef()
        hostdef.doc_id = "someid"
        hostdef.categories = {"access": Access.private,
                                "address": Address.fixed,
                                "storage": Storage.static}
        self.driver.save_document(hostdef)
        self.set_local("hostdef", hostdef)

        return self.process(setup)

    def testDefaultRequeriments(self):
        agent = self.get_local('agent')
        cats = agent._get_state().categories
        self.assertTrue("access" in cats)
        self.assertTrue("storage" in cats)
        self.assertTrue("address" in cats)
        self.assertEqual(cats["access"], Access.private)
        self.assertEqual(cats["address"], Address.fixed)
        self.assertEqual(cats["storage"], Storage.static)


@feat.register_agent('condition-agent')
class ConditionAgent(agent.BaseAgent):

    categories = {'access': Access.private,
                  'address': Address.fixed,
                  'storage': Storage.static}


@feat.register_descriptor('condition-agent')
class Descriptor(descriptor.Descriptor):
    pass


@feat.register_agent('conditionerror-agent')
class ConditionAgent2(agent.BaseAgent):

    categories = {'access': Access.none,
                  'address': Address.dynamic,
                  'storage': Storage.none}


@feat.register_descriptor('conditionerror-agent')
class Descriptor2(descriptor.Descriptor):
    pass


@common.attr(timescale=0.05)
class HostAgentCheckTest(common.SimulationTest):

    def prolog(self):
        setup = format_block("""
            agency = spawn_agency(hostdef=hostdef)

            test_desc = descriptor_factory('condition-agent')
            error_desc = descriptor_factory('conditionerror-agent')

            host_agent = agency.get_host_agent()

            host_agent.start_agent(test_desc)
            host_agent.start_agent(error_desc)
            """)

        hostdef = host.HostDef()
        hostdef.doc_id = "someid"
        hostdef.categories = {"access": Access.private,
                                "address": Address.fixed,
                                "storage": Storage.static}
        hostdef.resources = {"epu": 10}
        self.driver.save_document(hostdef)
        self.set_local("hostdef", hostdef)

        return self.process(setup)

    @defer.inlineCallbacks
    def testCheckRequeriments(self):

        def check_requeriments(categories):
            self.assertTrue("access" in categories)
            self.assertTrue("storage" in categories)
            self.assertTrue("address" in categories)
            self.assertEqual(categories["access"],
                             Access.private)
            self.assertEqual(categories["address"], Address.fixed)
            self.assertEqual(categories["storage"], Storage.static)

        host_agent = self.get_local('host_agent')
        check_requeriments(host_agent._get_state().categories)
        test_medium = yield self.driver.find_agent(self.get_local('test_desc'))
        test_agent = test_medium.get_agent()
        check_requeriments(test_agent.categories)


@feat.register_agent('contract-running-agent')
class RequestingAgent(agent.BaseAgent):

    @replay.mutable
    def request(self, state, shard, resc=dict(), desc=None):
        desc = desc or Descriptor3()
        if resc:
            desc.resources = params = dict(
                [key, resource.AllocatedScalar(val)]
                for key, val in resc.iteritems())
        f = self.save_document(desc)
        f.add_callback(lambda desc:
                       host.start_agent_in_shard(self, desc, shard))
        return f


@feat.register_descriptor('contract-running-agent')
class Descriptor3(descriptor.Descriptor):
    pass


@common.attr(timescale=0.05)
class SimulationStartAgentContract(common.SimulationTest):

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        test_desc = descriptor_factory('contract-running-agent')

        agency = spawn_agency()
        agency = spawn_agency()
        agency = spawn_agency()
        agent = agency.get_host_agent()
        agent.wait_for_ready()
        agent.start_agent(test_desc)
        """)
        yield self.process(setup)
        medium = first(self.driver.iter_agents('contract-running-agent'))
        self.agent = medium.get_agent()

    @defer.inlineCallbacks
    def testRunningContract(self):
        self.assertEqual(3, self.count_agents('host_agent'))
        self.assertEqual(1, self.count_agents('contract-running-agent'))
        shard = self.agent.get_shard_id()
        yield self.agent.request(shard)
        self.assertEqual(2, self.count_agents('contract-running-agent'))

    def testNonexistingShard(self):
        d = self.agent.request('some shard')
        self.assertFailure(d, host.NoHostFound)
        return d

    @defer.inlineCallbacks
    def testRunningWithSpecificResource(self):
        shard = self.agent.get_shard_id()
        res = dict(epu=20, core=1)
        recp = yield self.agent.request(shard, res)
        db = self.driver._database_connection
        doc = yield db.get_document(IRecipient(recp).key)
        self.assertIsInstance(doc.resources, dict)
        for key, val in res.iteritems():
            self.assertEqual(val, doc.resources[key].value)
        yield self.wait_for_idle(20)
        doc = yield db.reload_document(doc)

        host_id = doc.partners[0].recipient.key
        host_medium = yield self.driver.find_agent(host_id)
        host = host_medium.get_agent()
        _, allocated = yield host.list_resource()
        self.assertEqual(1, allocated['core'])

        # now use start_agent directly
        desc = Descriptor3(resources=dict(core=resource.AllocatedScalar(1)))
        desc = yield self.driver._database_connection.save_document(desc)
        self.info('starting')
        recp = yield host.start_agent(desc)
        desc = yield self.driver._database_connection.reload_document(desc)
        self.assertIsInstance(desc.resources, dict)
        self.assertEqual(['core'], desc.resources.keys())
        _, allocated = yield host.list_resource()
        self.assertEqual(2, allocated['core'])

    @defer.inlineCallbacks
    def testRestartingWithModifiedResource(self):
        shard = self.agent.get_shard_id()
        res = dict(epu=20, core=1)
        recp = yield self.agent.request(shard, res)
        desc = yield self.driver.get_document(IRecipient(recp).key)
        medium = yield self.driver.find_agent(recp)
        self.assertTrue(medium is not None)
        yield self.wait_for_idle(20)

        host = medium.get_agent().query_partners('hosts')[0]
        self.assertIsInstance(host, agent.HostPartner)
        yield medium.terminate_hard()

        res = dict(epu=10)
        desc = yield self.driver._database_connection.reload_document(desc)
        new_recp = yield self.agent.request(shard, res, desc)
        self.assertEqual(recp, new_recp)
        medium = yield self.driver.find_agent(recp)
        self.assertTrue(medium is not None)
        new_host = medium.get_agent().query_partners('hosts')[0]
        self.assertEqual(host, new_host)

        host_medium = yield self.driver.find_agent(host.recipient)
        host_a = host_medium.get_agent()
        _, allocated = host_a.list_resource()
        self.assertEqual(0, allocated['core'])
