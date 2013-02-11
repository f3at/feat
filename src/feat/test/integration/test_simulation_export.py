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
from feat.agents.export import export_agent
from feat.agents.shard import shard_agent
from feat.agents.base import agent, descriptor, replay, alert
from feat.agents.common import export
from feat.agencies import recipient
from feat.agents.application import feat

from feat.interface.agent import *


class TestAgent(agent.BaseAgent):

    @replay.mutable
    def initiate(self, state, dependency=None):
        state.dependency = dependency and recipient.IRecipient(dependency)

    @replay.journaled
    def startup(self, state):
        if state.dependency:
            return self.establish_partnership(state.dependency,
                                              our_role='link',
                                              partner_role='link')

    @replay.immutable
    def set_migration_dependencies(self, state, entry):
        if state.dependency:
            entry.add_dependency(state.dependency.key)

    @replay.immutable
    def get_migration_partners(self, state):
        partners = state.partners.query_with_role('all', 'link')
        return recipient.IRecipients(partners)


@feat.register_agent('test_worker_agent')
class ShutdownAgent(TestAgent):

    migratability = export.Migratability.shutdown


@feat.register_descriptor('test_worker_agent')
class Desc1(descriptor.Descriptor):
    pass


@feat.register_agent('test_signal_agent')
class ExportableAgent(TestAgent):

    migratability = export.Migratability.exportable


@feat.register_descriptor('test_signal_agent')
class Desc2(descriptor.Descriptor):
    pass


class Common(object):

    def _get_agent(self, agent_type):
        medium = first(self.driver.iter_agents(agent_type))
        return medium and medium.get_agent()

    @defer.inlineCallbacks
    def _get_agents_at(self, host):
        agents = [host]
        hosted_recp = yield host.get_hosted_recipients()
        for recp in hosted_recp:
            medium = yield self.driver.find_agent(recp)
            agents += [medium.get_agent()]
        defer.returnValue(agents)


@common.attr(timescale=0.2)
class ExportTest(common.SimulationTest, Common):

    def setUp(self):
        config = export_agent.ExportAgentConfiguration(
            doc_id = 'test-config',
            notification_period = 1)
        feat.initial_data(config)
        self.override_config('export_agent', config)
        return common.SimulationTest.setUp(self)

    @defer.inlineCallbacks
    def prolog(self):
        setup = text_helper.format_block("""
        agency1 = spawn_agency()
        host1 = agency1.get_host_agent()

        agency2 = spawn_agency()
        host2 = agency2.get_host_agent()

        host2.start_agent(descriptor_factory('export_agent'))
        host2.start_agent(descriptor_factory('alert_agent'))
        wait_for_idle()

        agency3 = spawn_agency()
        host3 = agency3.get_host_agent()
        host3.wait_for_ready()
        signal_desc = descriptor_factory('test_signal_agent')
        signal = host3.start_agent(signal_desc)
        host3.start_agent(descriptor_factory('test_worker_agent'),\
                          dependency=signal)

        agency4 = spawn_agency()
        host4 = agency4.get_host_agent()
        host4.wait_for_ready()
        host4.start_agent(descriptor_factory('test_worker_agent'),\
                          dependency=signal)
        wait_for_idle()
        """)
        yield self.process(setup)
        self.export_agent = self._get_agent('export_agent')
        self.host1 = self.get_local('host1')
        self.host2 = self.get_local('host2')
        self.host3 = self.get_local('host3')
        self.host4 = self.get_local('host4')

    @defer.inlineCallbacks
    def testJoiningMigrations(self):
        mig1 = yield self.export_agent.prepare_migration(
            recipient.IRecipient(self.host3))
        mig2 = yield self.export_agent.prepare_migration(
            recipient.IRecipient(self.host4))
        known = yield self.export_agent.get_known_migrations()
        self.assertEqual(set([mig1, mig2]), set(known))

        mig = yield self.export_agent.join_migrations([mig1, mig2])
        known = yield self.export_agent.get_known_migrations()
        self.assertEqual(set([mig]), set(known))

        self.assertEqual(5, len(mig.get_steps()))

        yield self.export_agent.cancel_migration(mig.get_id())
        signal = first(
            self.driver.iter_agents('test_signal_agent')).get_agent()
        self.assertFalse(signal.is_migrating())

    @defer.inlineCallbacks
    def testSimpleCheckinsAndCancels(self):
        # First query shard structure and make asserts on the result
        self.info("Starting test testcase.")
        resp = yield self.export_agent.get_shard_structure()
        self.assertEqual(1, len(resp))
        shard = resp[0]
        self.assertEqual(4, len(shard.hosts))
        for x in self.driver.iter_agents('host_agent'):
            self.assertTrue(x.get_agent_id() in shard.hosts)

        # Prepare migration of the host 0
        recp = yield self.host1.get_own_address()
        migration = yield self.export_agent.prepare_migration(recp)
        self.assertIsInstance(migration, export_agent.Migration)
        self.assertTrue(migration.is_completable())
        self.assertEqual(5, len(migration.get_steps()))
        agents = yield self._get_agents_at(self.host1)
        for agent in agents:
            self.assertTrue(agent.is_migrating())
        # Canceling the migration
        yield self.export_agent.cancel_migration(migration)
        for agent in agents:
            self.assertFalse(agent.is_migrating())

        # Prepare migration of host 1 (should fail as it runs export agent)
        self.info("Now preparing for host running export agent.")
        recp = yield self.host2.get_own_address()
        migration = yield self.export_agent.prepare_migration(recp)
        self.assertIsInstance(migration, export_agent.Migration)
        self.assertFalse(migration.is_completable())
        self.assertEqual(1, len(migration.get_steps()))
        agents = yield self._get_agents_at(self.host2)
        self.assertEqual(3, len(agents))
        yield self.wait_for_idle(4)
        for agent in agents:
            self.assertFalse(agent.is_migrating())

        # Prepare migration of host 2 (should be successful)
        self.info("Now preparing for host running signal agent.")
        recp = yield self.host3.get_own_address()
        migration = yield self.export_agent.prepare_migration(recp)
        self.assertIsInstance(migration, export_agent.Migration)
        self.assertTrue(migration.is_completable())
        self.assertEqual(4, len(migration.get_steps()))
        agents = yield self._get_agents_at(self.host3)
        self.assertEqual(3, len(agents))
        for agent in agents:
            self.assertTrue(agent.is_migrating())
        yield self.export_agent.cancel_migration(migration)
        for agent in agents:
            self.assertFalse(agent.is_migrating())

        # Prepare migration of host 3 (should be successful)
        self.info("Now preparing for host running only worker agent.")
        recp = yield self.host4.get_own_address()
        migration = yield self.export_agent.prepare_migration(recp)
        self.assertIsInstance(migration, export_agent.Migration)
        self.assertTrue(migration.is_completable())
        self.assertEqual(4, len(migration.get_steps()))
        agents = yield self._get_agents_at(self.host4)

        self.assertEqual(2, len(agents))
        for agent in agents:
            self.assertTrue(agent.is_migrating())
        yield self.export_agent.cancel_migration(migration)
        for agent in agents:
            self.assertFalse(agent.is_migrating())

    @defer.inlineCallbacks
    def testMigrateLocalAgents(self):
        # Prepare migration of the host 0
        recp = yield self.host1.get_own_address()
        migration = yield self.export_agent.prepare_migration(
            recp, host_cmd='special command')

        # first 4 steps involving migration of the structural agents
        for expected in range(3, -1, -1):
            migration = yield self.export_agent.apply_next_step(migration)
            self.assertTrue(migration.get_steps()[3-expected].applied)
            yield self.wait_for_idle(10)
            hosted_recp = yield self.host1.get_hosted_recipients()
            num = len(hosted_recp)
            self.assertEqual(expected, num)

        yield self.wait_for(self.export_agent.has_empty_outbox, 20)
        yield self.wait_for_idle(10)

        for agent_type in ('shard_agent', 'raage_agent', 'monitor_agent', ):
            agent = yield self._get_agent(agent_type)
            host_partners = agent.query_partners_with_role('all', 'host')
            self.assertEqual(1, len(host_partners), host_partners)
            self.assertNotEqual(host_partners[0].recipient, recp, agent_type)

        # now perform the last step - termination of the host
        migration = yield self.export_agent.apply_next_step(migration)
        yield self.wait_for_idle(10)
        self.assertEqual(AgencyAgentState.terminated,
                         self.host1.get_agent_status())
        agency1 = self.get_local('agency1')
        self.assertEqual('special command', agency1.get_upgrade_command())
        self.assertEqual(3, self.count_agents('host_agent'))
        shard = yield self._get_agent('shard_agent')
        self.assertEqual(3, len(shard.query_partners('hosts')))
        self.assertEqual(3, len(list(self.driver.iter_agencies())))

    @defer.inlineCallbacks
    def testExportingAgent(self):
        recp = self.host3.get_own_address()
        migration = yield self.export_agent.prepare_migration(
            recp, migration_agent=None)
        self.assertTrue(migration.is_completable())
        signal = yield self._get_agent('test_signal_agent')
        self.assertIsNot(None, signal)
        # apply first step (export test_signal_agent), it will just get
        # terminated as there is no import agent
        migration = yield self.export_agent.apply_next_step(migration)
        yield self.wait_for(self.export_agent.has_empty_outbox, 10)
        yield self.wait_for_idle(10)
        signal = yield self._get_agent('test_signal_agent')
        self.assertIs(None, signal)
        agents = yield self._get_agents_at(self.host3)
        # one worker left
        self.assertEqual(2, len(agents))
        monitor = yield self._get_agent('monitor_agent')
        p = yield monitor.find_partner(migration.get_steps()[0].recipient)
        self.assertIs(None, p)

        # just finish the migration
        while not migration.is_complete():
            migration = yield self.export_agent.apply_next_step(migration)
            yield self.wait_for(self.export_agent.has_empty_outbox, 10)
            yield self.wait_for_idle(10)
        self.assertEqual(0, self.count_agents('test_worker_agent'))
        self.assertEqual(3, len(list(self.driver.iter_agencies())))


@common.attr(timescale=0.2)
class TestShutingDownShard(common.SimulationTest, Common):

    def setUp(self):
        config = export_agent.ExportAgentConfiguration(
            doc_id = 'test-export-config',
            notification_period = 1)
        feat.initial_data(config)
        self.override_config('export_agent', config)

        config = shard_agent.ShardAgentConfiguration(
            doc_id = 'test-shard-config',
            hosts_per_shard = 1)
        feat.initial_data(config)
        self.override_config('shard_agent', config)

        return common.SimulationTest.setUp(self)

    def prolog(self):
        setup = text_helper.format_block("""
        # starts 2 shards, second of which runs the export agent
        agency1 = spawn_agency()
        host1 = agency1.get_host_agent()

        agency1 = spawn_agency()
        host2 = agency1.get_host_agent()
        host2.start_agent(descriptor_factory('export_agent'))

        wait_for_idle()
        """)
        return self.process(setup)

    @defer.inlineCallbacks
    def testShutdownWholeShard(self):
        # validate prolog
        self.assertEqual(2, self.count_agents("host_agent"))
        self.assertEqual(2, self.count_agents("monitor_agent"))
        self.assertEqual(2, self.count_agents("shard_agent"))
        self.assertEqual(2, self.count_agents("raage_agent"))
        self.assertEqual(1, self.count_agents("export_agent"))
        export_agent = yield self._get_agent('export_agent')

        # get migration plan
        host1 = self.get_local('host1')
        recp = recipient.IRecipient(host1)
        migration = yield export_agent.prepare_migration(recp)
        self.assertTrue(migration.is_completable())
        # should only consist of termination of the host
        self.assertEqual(1, len(migration.get_steps()))

        migration = yield export_agent.apply_next_step(migration)
        self.assertTrue(migration.is_complete())
        yield self.wait_for_idle(20)

        self.assertEqual(1, self.count_agents("host_agent"))
        self.assertEqual(1, self.count_agents("monitor_agent"))
        self.assertEqual(1, self.count_agents("shard_agent"))
        self.assertEqual(1, self.count_agents("raage_agent"))
        self.assertEqual(1, self.count_agents("export_agent"))
        self.assertEqual(1, len(list(self.driver.iter_agencies())))

        # check that key agents sent goodbyes
        monitor = yield self._get_agent('monitor_agent')
        p = monitor.query_partners('monitors')
        self.assertEqual(0, len(p))

        shard = yield self._get_agent('shard_agent')
        p = shard.query_partners('neighbours')
        self.assertEqual(0, len(p))
