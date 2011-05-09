from feat import everything
from feat.test.integration import common
from feat.common.text_helper import format_block
from feat.common import defer, first, time


@common.attr(timescale=0.05)
class StructuralPartners(common.SimulationTest):

    timeout = 30

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        spawn_agency()
        _.start_agent(descriptor_factory('host_agent'))

        wait_for_idle()

        spawn_agency()
        _.start_agent(descriptor_factory('host_agent'))

        wait_for_idle()
        """)

        yield self.process(setup)
        yield self.wait_for_idle(20)
        self.raage_medium = first(self.driver.iter_agents('raage_agent'))
        self.shard_medium = first(self.driver.iter_agents('shard_agent'))

    def testValidateProlog(self):
        self.assertEqual(1, self.count_agents('shard_agent'))
        self.assertEqual(2, self.count_agents('host_agent'))
        self.assertEqual(1, self.count_agents('raage_agent'))

    @defer.inlineCallbacks
    def testRaageGetsRestarted(self):
        yield self.raage_medium._terminate()
        yield self.wait_for_idle(10)
        self.assertEqual(1, self.count_agents('raage_agent'))

    @common.attr(timeout=80)
    @defer.inlineCallbacks
    def testArmagedon(self):
        '''
        In this test we kill the host with Raage and Shard.
        Then we assert that they were recreated.
        '''
        d1 = self.raage_medium._terminate()
        d2 = self.shard_medium._terminate()
        d3 = first(self.driver.iter_agents('host_agent'))._terminate()
        yield defer.DeferredList([d1, d2, d3])

        yield self.wait_for_idle(30)
        self.assertEqual(1, self.count_agents('raage_agent'))
        self.assertEqual(1, self.count_agents('shard_agent'))
        self.assertEqual(1, self.count_agents('host_agent'))
