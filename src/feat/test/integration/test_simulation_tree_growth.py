# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.internet import defer

from feat.common import format_block
from feat.test.integration import common
from feat.test.common import attr
from feat.agents.host import host_agent
from feat.agents.shard import shard_agent


class TreeGrowthSimulation(common.SimulationTest):

    timeout = 10
    hosts_per_shard = 10
    children_per_shard = 2

    start_host_agent = format_block("""
        agency = spawn_agency()
        agency.start_agent(descriptor_factory('host_agent'))
        """)

    def prolog(self):
        setup = format_block("""
        agency = spawn_agency()
        shard_desc = descriptor_factory('shard_agent', 'root')
        host_desc = descriptor_factory('host_agent')
        agency.start_agent(shard_desc)
        agency.start_agent(host_desc)
        """)
        return self.process(setup)

    def testValidateProlog(self):
        agency = self.get_local('agency')
        self.assertEqual(2, len(agency._agents))
        self.assertIsInstance(agency._agents[0].agent, shard_agent.ShardAgent)
        self.assertIsInstance(agency._agents[1].agent, host_agent.HostAgent)

        self.assert_all_agents_in_shard(agency, 'root')

    @defer.inlineCallbacks
    def testFillUpTheRootShard(self):
        shard_agent = self.get_local('agency')._agents[0].agent
        for i in range(2, self.hosts_per_shard + 1):
            yield self.process(self.start_host_agent)
            self.assertEqual(i,
                    shard_agent._get_state().resources.allocated()['hosts'])

        self.assertEqual(self.hosts_per_shard, len(self.driver._agencies))
        for agency in self.driver._agencies[1:]:
            self.assert_all_agents_in_shard(agency, 'root')

    @defer.inlineCallbacks
    def testStartNewShard(self):
        fillup_root_shard = self.start_host_agent * (self.hosts_per_shard - 1)
        yield self.process(fillup_root_shard)
        yield self.process(self.start_host_agent)

        last_agency = self.driver._agencies[-1]
        self.assertEqual(2, len(last_agency._agents))
        self.assertIsInstance(last_agency._agents[0].agent,
                              host_agent.HostAgent)
        self.assertIsInstance(last_agency._agents[1].agent,
                              shard_agent.ShardAgent)
        host = last_agency._agents[0]
        shard = (host.get_descriptor()).shard
        self.assert_all_agents_in_shard(last_agency, shard)

    @attr(skip="to be done when the serialization to json is there")
    @defer.inlineCallbacks
    def testStartLevel2(self):
        # fill all the places in root shard, on shard lvl 1 + 1 hosts on lvl2
        number_of_hosts_to_start =\
            ((self.children_per_shard + 1) * self.hosts_per_shard)

        script = self.start_host_agent * number_of_hosts_to_start
        yield self.process(script)

        root_shard_agencies = self.driver._agencies[0:self.hosts_per_shard]
        for agency in root_shard_agencies:
            self.assert_all_agents_in_shard(agency, 'root')

        for lvl1child in range(self.children_per_shard):
            first_agency_in_shard = self.driver._agencies[
                self.hosts_per_shard * (lvl1child + 1)]
            desc = (first_agency_in_shard._agents[1].agent.\
                     medium.get_descriptor())
            self.info(desc)
#            self.assertEqual('root', desc.parent)
#            self.assert_all_agents_in_shard(agency, desc.shard)

    @defer.inlineCallbacks
    def testFillupTwoShards(self):
        fillup_two_shards = self.start_host_agent *\
                            (2 * self.hosts_per_shard - 1)
        yield self.process(fillup_two_shards)

        last_agency = self.driver._agencies[-1]
        shard = (last_agency._agents[0].get_descriptor()).shard
        agency_for_second_shard = self.driver._agencies[-self.hosts_per_shard:]
        for agency in agency_for_second_shard:
            self.assert_all_agents_in_shard(agency, shard)

    def assert_all_agents_in_shard(self, agency, shard):
        expected_bindings_to_shard = {
            host_agent.HostAgent: 1,
            shard_agent.ShardAgent: 2}
        expected_bindings_to_lobby = {
            host_agent.HostAgent: 0,
            shard_agent.ShardAgent:\
                lambda desc: (desc.parent is None and 1) or 0}

        for agent in agency._agents:
            desc = agent.get_descriptor()
            self.assertEqual(shard, desc.shard)
            m = agent._messaging
            agent_type = agent.agent.__class__

            expected = expected_bindings_to_shard[agent_type]
            if callable(expected):
                expected = expected(agent.get_descriptor())
            got = len(m.get_bindings(shard))
            self.assertEqual(expected, got,
                        '%r should have %d bindings to shard: %s but had %d' %\
                        (agent_type.__name__, expected, shard, got, ))

            expected = expected_bindings_to_lobby[agent_type]
            if callable(expected):
                expected = expected(agent.get_descriptor())
            got = len(m.get_bindings('lobby'))
            self.assertEqual(expected, got,
                            '%r living in shard: %r should have %d '
                             'bindings to "lobby" but had %d' %\
                            (agent_type.__name__, shard, expected, got, ))
