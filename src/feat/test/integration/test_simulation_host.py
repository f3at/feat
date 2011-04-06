import socket

from twisted.internet import defer
from twisted.python import failure

from feat.test.integration import common

from feat.agents.base import agent, descriptor, replay
from feat.agents.common import host
from feat.agents.host import host_agent
from feat.common.text_helper import format_block

from feat.interface.recipient import *


class HostAgentTests(common.SimulationTest):

    NUM_PORTS = 999

    def prolog(self):
        setup = format_block("""
        agency = spawn_agency()
        desc1 = descriptor_factory('host_agent')
        medium = agency.start_agent(desc1)
        agent = medium.get_agent()
        desc2 = medium.get_descriptor()
        """)
        return self.process(setup)

    def testValidateProlog(self):
        agents = [x for x in self.driver.iter_agents()]
        self.assertEqual(1, len(agents))

    def testDefaultResources(self):
        agent = self.get_local('agent')
        totals = agent._get_state().resources.get_totals()
        self.assertTrue("host" in totals)
        self.assertTrue("epu" in totals)
        self.assertTrue("core" in totals)
        self.assertTrue("mem" in totals)

    def testHostname(self):
        expected = socket.gethostbyaddr(socket.gethostname())[0]
        self.assertEqual(self.get_local('desc1').hostname, None)
        self.assertEqual(self.get_local('desc2').hostname, expected)
        agent = self.get_local('agent')
        self.assertEqual(agent.get_hostname(), expected)

    @defer.inlineCallbacks
    def testAllocatePorts(self):
        agent = self.get_local('agent')
        ports = yield agent.allocate_ports(10)
        self.assertEqual(agent.get_num_free_ports(), self.NUM_PORTS - 10)
        self.assertEqual(len(ports), 10)

    @defer.inlineCallbacks
    def testAllocatePortsAndRelease(self):
        agent = self.get_local('agent')
        ports = yield agent.allocate_ports(10)
        self.assertEqual(agent.get_num_free_ports(), self.NUM_PORTS - 10)
        agent.release_ports(ports)
        self.assertEqual(agent.get_num_free_ports(), self.NUM_PORTS)

    def testSetPortsUsed(self):
        agent = self.get_local('agent')
        ports = range(5000, 5010)
        agent.set_ports_used(ports)
        self.assertEqual(agent.get_num_free_ports(), self.NUM_PORTS - 10)
        agent.release_ports(ports)
        self.assertEqual(agent.get_num_free_ports(), self.NUM_PORTS)


class HostAgentDefinitionTests(common.SimulationTest):

    def prolog(self):
        setup = format_block("""
        agency1 = spawn_agency()
        desc1 = descriptor_factory('host_agent')
        medium1 = agency1.start_agent(desc1, hostdef=hostdef)
        agent1 = medium1.get_agent()

        agency2 = spawn_agency()
        desc2 = descriptor_factory('host_agent')
        medium2 = agency2.start_agent(desc2, hostdef=hostdef_id)
        agent2 = medium2.get_agent()
        """)

        hostdef = host.HostDef()
        hostdef.doc_id = "someid"
        hostdef.resources = {"spam": 999, "bacon": 42, "eggs": 3}
        self.driver.save_document(hostdef)
        self.set_local("hostdef", hostdef)
        self.set_local("hostdef_id", "someid")

        return self.process(setup)

    def testValidateProlog(self):
        agents = [x for x in self.driver.iter_agents()]
        self.assertEqual(2, len(agents))

    def testDefaultResources(self):

        def check_resources(resources):
            totals = resources.get_totals()
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
