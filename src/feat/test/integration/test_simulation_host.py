import socket

from twisted.internet import defer

from feat import everything
from feat.test.integration import common

from feat.agents.base import agent, descriptor, document
from feat.agents.common import host
from feat.common.text_helper import format_block

from feat.interface.recipient import *
from feat.interface.agent import Access, Address, Storage


class HostAgentTests(common.SimulationTest):

    NUM_PORTS = 999

    def prolog(self):
        setup = format_block("""
        agency = spawn_agency()
        desc1 = descriptor_factory('host_agent')
        medium = agency.start_agent(desc1, run_startup=False)
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
        self.assertTrue("bandwith" in totals)
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
        medium1 = agency1.start_agent(desc1, hostdef=hostdef, \
        run_startup=False)
        agent1 = medium1.get_agent()

        agency2 = spawn_agency()
        desc2 = descriptor_factory('host_agent')
        medium2 = agency2.start_agent(desc2, hostdef=hostdef_id, \
        run_startup=False)
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


class HostAgentRequerimentsTest(common.SimulationTest):

    def prolog(self):
        setup = format_block("""
            agency = spawn_agency()
            desc = descriptor_factory('host_agent')
            medium = agency.start_agent(desc, hostdef=hostdef,\
                                        run_startup=False)
            agent = medium.get_agent()
            """)

        hostdef = host.HostDef()
        hostdef.doc_id = "someid"
        hostdef.categories = {"access": Access.private,
                                "address": Address.fixed,
                                "storage": Storage.static}
        self.driver.save_document(hostdef)
        self.set_local("hostdef", hostdef)

        return self.process(setup)

    def testValidateProlog(self):
        agents = [x for x in self.driver.iter_agents()]
        self.assertEqual(1, len(agents))

    def testDefaultRequeriments(self):
        agent = self.get_local('agent')
        cats = agent._get_state().categories
        self.assertTrue("access" in cats)
        self.assertTrue("storage" in cats)
        self.assertTrue("address" in cats)
        self.assertEqual(cats["access"], Access.private)
        self.assertEqual(cats["address"], Address.fixed)
        self.assertEqual(cats["storage"], Storage.static)


@agent.register('condition-agent')
class ConditionAgent(agent.BaseAgent):

    categories = {'access': Access.private,
                  'address': Address.fixed,
                  'storage': Storage.static}


@document.register
class Descriptor(descriptor.Descriptor):

    document_type = 'condition-agent'


@agent.register('conditionerror-agent')
class ConditionAgent(agent.BaseAgent):

    categories = {'access': Access.none,
                  'address': Address.dynamic,
                  'storage': Storage.none}


@document.register
class Descriptor(descriptor.Descriptor):

    document_type = 'conditionerror-agent'


class HostAgentCheckTest(common.SimulationTest):

    def prolog(self):
        setup = format_block("""
            agency = spawn_agency()

            host_desc = descriptor_factory('host_agent')
            test_desc = descriptor_factory('condition-agent')
            error_desc = descriptor_factory('conditionerror-agent')

            host_medium = agency.start_agent(host_desc, hostdef=hostdef, \
                                             run_startup=False)
            host_agent = host_medium.get_agent()

            host_agent.start_agent(test_desc)
            host_agent.start_agent(error_desc)
            """)

        hostdef = host.HostDef()
        hostdef.doc_id = "someid"
        hostdef.categories = {"access": Access.private,
                                "address": Address.fixed,
                                "storage": Storage.static}
        self.driver.save_document(hostdef)
        self.set_local("hostdef", hostdef)

        return self.process(setup)

    def testValidateProlog(self):
        agents = [x for x in self.driver.iter_agents()]
        self.assertEqual(2, len(agents))

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
        test_medium = self.driver.find_agent(self.get_local('test_desc'))
        test_agent = test_medium.get_agent()
        check_requeriments(test_agent.categories)
