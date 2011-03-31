import socket

from twisted.internet import defer
from twisted.python import failure

from feat.test.integration import common

from feat.agents.base import agent, descriptor, replay
from feat.agents.host import host_agent
from feat.common.text_helper import format_block

from feat.interface.recipient import *


class HostAgentTests(common.SimulationTest):

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

    def testHostname(self):
        expected = socket.gethostbyaddr(socket.gethostname())[0]
        self.assertEqual(self.get_local('desc1').hostname, None)
        self.assertEqual(self.get_local('desc2').hostname, expected)
        agent = self.get_local('agent')
        self.assertEqual(agent.get_hostname(), expected)
