# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.internet import defer

from feat.common import format_block, delay
from feat.test.integration import common
from feat.agents.host import host_agent
from feat.agents.shard import shard_agent
from feat.agents.base import recipient


class Common(object):

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
            self.assertEqual(shard, desc.shard, str(type(agent.agent)))
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


class TreeGrowthSimulation(common.SimulationTest, Common):

    # Timeout is intentionaly set to high. Some of theese tests take a lot
    # of time running with --coverage on buildbot (virtualized machine)
    timeout = 100
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
        agency.snapshot_agents()
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

    @defer.inlineCallbacks
    def testStartLevel2(self):
        # fill all the places in root shard, on shard lvl 1
        # and create the first hosts on lvl 2
        number_of_hosts_to_start =\
            ((self.children_per_shard + 1) * self.hosts_per_shard)

        script = self.start_host_agent * number_of_hosts_to_start
        yield self.process(script)

        root_shard_agencies = self.driver._agencies[0:self.hosts_per_shard]
        for agency in root_shard_agencies:
            self.assert_all_agents_in_shard(agency, 'root')

        # validate root shard
        root_shard_desc = yield self.driver.reload_document(
            self.get_local('shard_desc'))
        self.assertEqual(self.children_per_shard,
                         len(root_shard_desc.children))
        self.assertEqual(self.hosts_per_shard, len(root_shard_desc.hosts))
        self.assertIsInstance(root_shard_desc.hosts[0],
                              recipient.BaseRecipient)

        # validate lvl 1
        for child in root_shard_desc.children:
            self.assertIsInstance(child, recipient.BaseRecipient)
            desc = yield self.driver.get_document(child.key)
            self.assertEqual(self.hosts_per_shard, len(root_shard_desc.hosts))
            self.assertEqual(desc.parent.key, root_shard_desc.doc_id)
            self.assertEqual(desc.parent.shard, root_shard_desc.shard)
            for host in desc.hosts:
                self.assertIsInstance(host, recipient.BaseRecipient)
                host_desc = yield self.driver.get_document(host.key)
                self.assertEqual(host_desc.shard, child.shard)
                self.assertEqual(host.shard, child.shard)

                yield self.process(format_block("""
                host_agency = None
                host_agency = find_agency('%s')
                """) % str(host.key))
                host_agency = self.get_local('host_agency')
                self.assertTrue(host_agency is not None)
                self.assert_all_agents_in_shard(host_agency, host.shard)

        #validate last agency (on lvl 2)
        parent = root_shard_desc.children[0]
        agency = self.driver._agencies[-1]
        self.assertEqual(2, len(agency._agents))
        self.assertIsInstance(agency._agents[0].agent,
                              host_agent.HostAgent)
        self.assertIsInstance(agency._agents[1].agent,
                              shard_agent.ShardAgent)
        desc_id = agency._agents[1]._descriptor.doc_id
        self.info(agency._database._get_doc(desc_id))
        desc = yield self.driver.get_document(desc_id)
        self.info(desc_id)
        self.assertIsInstance(desc.parent, (recipient.RecipientFromAgent,
                                            recipient.Agent, ))
        self.assertEqual(parent.key, desc.parent.key)
        self.assertEqual(1, len(desc.hosts))
        self.assertEqual(0, len(desc.children))

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


class SimulationHostBeforeShard(common.SimulationTest, Common):

    timeout = 100

    def prolog(self):
        pass

    @defer.inlineCallbacks
    def testHAKeepsTillShardAgentAppears(self):
        delay.time_scale = 0.01

        setup = format_block("""
        agency = spawn_agency()
        host_desc = descriptor_factory('host_agent')
        ha = agency.start_agent(host_desc)
        """)
        d = self.process(setup)
        agency = self.get_local('agency')
        ha = agency._agents[0]

        # check the retries 3 times
        yield self.cb_after(None, ha, 'initiate_protocol')
        self.info('First contract failed.')
        yield self.cb_after(None, ha, 'initiate_protocol')
        yield self.cb_after(None, ha, 'initiate_protocol')

        script = format_block("""
        shard_desc = descriptor_factory('shard_agent', 'root')
        agency = spawn_agency()
        agency.start_agent(shard_desc)
        """)
        # get additional parser - the original is locked in initiated
        # host agent
        parser = self.driver.get_additional_parser()
        parser.dataReceived(script)

        # after shard agent has appeared it is possible to finish
        # initializing the host agent
        yield d

        self.assertEqual(1, len(agency._agents))
        self.assertIsInstance(agency._agents[0].agent, host_agent.HostAgent)
        self.assert_all_agents_in_shard(agency, 'root')
