# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.internet import defer

from feat import everything
from feat.common import delay, first
from feat.test.integration import common
from feat.interface.protocols import InitiatorFailed
from feat.common.text_helper import format_block
from feat.agents.base import recipient, dbtools
from feat.agents.common import host


@common.attr('slow')
class SingleHostMonitorSimulation(common.SimulationTest):

    timeout = 20

    @defer.inlineCallbacks
    def prolog(self):
        delay.time_scale = 0.8
        setup = format_block("""
        load('feat.test.integration.monitor')

        agency = spawn_agency()

        host_desc = descriptor_factory('host_agent')
        req_desc = descriptor_factory('request_monitor_agent')

        host_medium = agency.start_agent(host_desc)
        host_agent = host_medium.get_agent()

        host_agent.wait_for_ready()
        host_agent.start_agent(req_desc)
        """)

        yield self.process(setup)
        yield self.wait_for_idle(10)

        monitor_medium = list(self.driver.iter_agents('monitor_agent'))[0]
        self.monitor_agent = monitor_medium.get_agent()

        self.req_agent = self.driver.find_agent(
                self.get_local('req_desc')).get_agent()

    @defer.inlineCallbacks
    def tearDown(self):
        for x in self.driver.iter_agents():
            yield x.wait_for_listeners_finish()
        yield common.SimulationTest.tearDown(self)

    def testValidateProlog(self):
        self.assertEqual(1, self.count_agents('host_agent'))
        self.assertEqual(1, self.count_agents('shard_agent'))
        self.assertEqual(1, self.count_agents('monitor_agent'))
        self.assertEqual(1, self.count_agents('request_monitor_agent'))

    @defer.inlineCallbacks
    def testPartnerMonitor(self):
        yield self.req_agent.request_monitor()
        partners = self.monitor_agent.get_descriptor().partners
        self.assertEqual(3, len(partners))
