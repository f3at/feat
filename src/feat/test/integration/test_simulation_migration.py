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
from feat.common import defer, text_helper, first, fiber
from feat.agents.export import export_agent
from feat.agents.shard import shard_agent
from feat.agents.base import dbtools, descriptor, replay, agent, recipient
from feat.agents.common import export, start_agent, host

# this import is here to get the
from feat.test.integration.test_simulation_export import TestAgent


@agent.register('test_exportable_agent')
class ExportableAgent(TestAgent):

    migratability = export.Migratability.exportable
    resources = {"epu": 100}

    @replay.mutable
    def startup(self, state):
        own = self.get_own_address()
        f = fiber.succeed()
        for x in range(2):
            desc = D2()
            f.add_callback(fiber.drop_param, self.save_document, desc)
            f.add_callback(fiber.inject_param, 2, self.initiate_protocol,
                           start_agent.GloballyStartAgent, dependency=own)
        return f


@descriptor.register('test_exportable_agent')
class D1(descriptor.Descriptor):
    pass


@descriptor.register('test_child_agent')
class D2(descriptor.Descriptor):
    pass


@agent.register('test_child_agent')
class ChildAgent(TestAgent):

    migratability = export.Migratability.shutdown


@common.attr('slow', timescale=0.2)
class TestMigration(common.SimulationTest):

    def setUp(self):
        config = export_agent.ExportAgentConfiguration(
            doc_id = 'test-export-config',
            sitename = 'testing_site',
            notification_period = 1)
        dbtools.initial_data(config)
        self.override_config('export_agent', config)

        config = shard_agent.ShardAgentConfiguration(
            doc_id = 'test-shard-config',
            hosts_per_shard = 2)
        dbtools.initial_data(config)
        self.override_config('shard_agent', config)

        return common.SimulationTest.setUp(self)

    @defer.inlineCallbacks
    def prolog(self):
        setup = text_helper.format_block("""
        agency = spawn_agency()
        agency.disable_protocol('setup-monitoring', 'Task')
        agency.start_agent(descriptor_factory('host_agent'))
        host1 = _.get_agent()
        wait_for_idle()

        agency = spawn_agency()
        agency.disable_protocol('setup-monitoring', 'Task')
        agency.start_agent(descriptor_factory('host_agent'))
        wait_for_idle()

        host1.start_agent(descriptor_factory('test_exportable_agent'))
        wait_for_idle()

        agency = spawn_agency()
        agency.disable_protocol('setup-monitoring', 'Task')
        agency.start_agent(descriptor_factory('host_agent'))
        wait_for_idle()

        agency = spawn_agency()
        agency.disable_protocol('setup-monitoring', 'Task')
        agency.start_agent(descriptor_factory('host_agent'))
        host2 = _.get_agent()
        host2.start_agent(descriptor_factory('export_agent'))
        wait_for_idle()
        host2.start_agent(descriptor_factory('migration_agent'))
        wait_for_idle()
        """)
        yield self.process(setup)

        self.export = first(
            self.driver.iter_agents('export_agent')).get_agent()
        self.migration = first(
            self.driver.iter_agents('migration_agent')).get_agent()
        self.assertEqual(1, self.count_agents('test_exportable_agent'))
        self.assertEqual(2, self.count_agents('test_child_agent'))
        self.host1 = self.get_local('host1')
        self.host2 = self.get_local('host2')

    @defer.inlineCallbacks
    def testMigrateOutShard(self):
        exports = self.migration._get_exports()
        self.assertEqual(1, len(exports.entries))
        self.assertIn('testing_site', exports.entries)

        yield self.migration.set_current('testing_site')
        shards = yield self.migration.get_structure()

        # we will migrate first shard (with only migratable agents)
        shard = recipient.IRecipient(self.host1).route
        to_migrate = first(x for x in shards if x.shard == shard)
        self.assertIsNot(None, to_migrate)

        migration = yield self.migration.prepare_shard_migration(to_migrate)
        self.assertTrue(migration.completable)
        self.assertFalse(migration.completed)
        show = yield self.migration.show_migration(migration.ident)
        self.assertIsInstance(show, str)

        # apply first step manually just to check it works
        yield self.migration.apply_migration_step(migration, 0)

        yield self.migration.apply_migration(migration)
        yield self.wait_for_idle(10)

        self.assertEqual(1, self.count_agents('test_exportable_agent'))
        self.assertEqual(2, self.count_agents('test_child_agent'))
        self.assertEqual(2, self.count_agents('host_agent'))
        self.assertEqual(1, self.count_agents('shard_agent'))
        self.assertEqual(1, self.count_agents('raage_agent'))
        self.assertEqual(1, self.count_agents('monitor_agent'))

    @defer.inlineCallbacks
    def testMigrateOutShardWhichIsNotMigratable(self):
        yield self.migration.set_current('testing_site')
        shards = yield self.migration.get_structure()

        # we will migrate second shard (with migration and export agent)
        shard = recipient.IRecipient(self.host2).route
        to_migrate = first(x for x in shards if x.shard == shard)
        self.assertIsNot(None, to_migrate)

        migration = yield self.migration.prepare_shard_migration(to_migrate)
        real_migration = self.export._get_migration(migration.ident)

        self.assertEqual(4, len(real_migration.get_steps()))

        yield self.migration.apply_migration(migration)
        yield self.wait_for_idle(10)

        self.assertEqual(1, self.count_agents('test_exportable_agent'))
        self.assertEqual(2, self.count_agents('test_child_agent'))
        self.assertEqual(3, self.count_agents('host_agent'))
        self.assertEqual(2, self.count_agents('shard_agent'))
        self.assertEqual(2, self.count_agents('raage_agent'))
        self.assertEqual(2, self.count_agents('monitor_agent'))


@common.attr('slow', timescale=0.2)
class TestMigrationBetweenClusters(common.MultiClusterSimulation):

    configurable_attributes = \
        common.MultiClusterSimulation.configurable_attributes + \
        ['epu_in_new_cluster']
    epu_in_new_cluster = 50

    def setUp(self):
        config = export_agent.ExportAgentConfiguration(
            doc_id = 'test-export-config',
            sitename = 'testing_site',
            notification_period = 1)
        dbtools.initial_data(config)
        self.override_config('export_agent', config)

        config = shard_agent.ShardAgentConfiguration(
            doc_id = 'test-shard-config',
            hosts_per_shard = 2)
        dbtools.initial_data(config)
        self.override_config('shard_agent', config)

        return common.MultiClusterSimulation.setUp(self)

    @defer.inlineCallbacks
    def prolog(self):
        setup1 = text_helper.format_block("""
        agency = spawn_agency()
        agency.disable_protocol('setup-monitoring', 'Task')
        agency.start_agent(descriptor_factory('host_agent'))
        host1 = _.get_agent()
        wait_for_idle()

        agency = spawn_agency()
        agency.disable_protocol('setup-monitoring', 'Task')
        agency.start_agent(descriptor_factory('host_agent'))
        wait_for_idle()

        host1.start_agent(descriptor_factory('test_exportable_agent'))
        wait_for_idle()

        agency = spawn_agency()
        agency.disable_protocol('setup-monitoring', 'Task')
        agency.start_agent(descriptor_factory('host_agent'))
        wait_for_idle()

        agency = spawn_agency()
        agency.disable_protocol('setup-monitoring', 'Task')
        agency.start_agent(descriptor_factory('host_agent'))
        host2 = _.get_agent()
        host2.start_agent(descriptor_factory('export_agent'))
        wait_for_idle()
        """)
        yield self.process(self.drivers[0], setup1)

        setup2 = text_helper.format_block("""
        agency = spawn_agency()
        agency.disable_protocol('setup-monitoring', 'Task')
        agency.start_agent(descriptor_factory('host_agent'), hostdef=hostdef1)
        host = _.get_agent()
        wait_for_idle()
        host.start_agent(descriptor_factory('alert_agent'))
        host.start_agent(descriptor_factory('migration_agent'))
        wait_for_idle()
        """)

        hd1 = host.HostDef()
        hd1.resources['epu'] = self.epu_in_new_cluster
        self.drivers[1].set_local('hostdef1', hd1)
        hd2 = host.HostDef()
        hd2.resources['epu'] = 500
        self.drivers[1].set_local('hostdef2', hd2)
        yield self.process(self.drivers[1], setup2)

        self.export = first(
            self.drivers[0].iter_agents('export_agent')).get_agent()
        self.migration = first(
            self.drivers[1].iter_agents('migration_agent')).get_agent()
        self.host1 = self.drivers[0].get_local('host1')
        self.host2 = self.drivers[0].get_local('host2')
        self.alert = first(
            self.drivers[1].iter_agents('alert_agent')).get_agent()

        recp = yield self.export.get_own_address('tunnel')
        self.assertIsInstance(recp, recipient.Recipient)
        yield self.migration.handshake(recp)
        yield self.migration.set_current('testing_site')

    @common.attr(save_journal=True, epu_in_new_cluster=500)
    @defer.inlineCallbacks
    def testMigrateOutShard(self):
        self.assertEqual(1,
                         self.drivers[0].count_agents('test_exportable_agent'))
        self.assertEqual(2, self.drivers[0].count_agents('test_child_agent'))
        self.assertEqual(4, self.drivers[0].count_agents('host_agent'))
        self.assertEqual(2, self.drivers[0].count_agents('shard_agent'))
        self.assertEqual(2, self.drivers[0].count_agents('raage_agent'))
        self.assertEqual(2, self.drivers[0].count_agents('monitor_agent'))

        exports = self.migration._get_exports()
        self.assertEqual(1, len(exports.entries))
        self.assertIn('testing_site', exports.entries)

        yield self.migration.set_current('testing_site')
        shards = yield self.migration.get_structure()

        # we will migrate first shard (with only migratable agents)
        shard = recipient.IRecipient(self.host1).route
        to_migrate = first(x for x in shards if x.shard == shard)
        self.assertIsNot(None, to_migrate)

        migration = yield self.migration.prepare_shard_migration(to_migrate)
        self.assertTrue(migration.completable)
        self.assertFalse(migration.completed)
        show = yield self.migration.show_migration(migration.ident)
        self.assertIsInstance(show, str)

        # apply first step manually just to check it works
        yield self.migration.apply_migration_step(migration, 0)

        yield self.migration.apply_migration(migration)
        yield self.wait_for_idle(10)

        self.assertEqual(1,
                         self.drivers[1].count_agents('test_exportable_agent'))
        self.assertEqual(2, self.drivers[1].count_agents('test_child_agent'))
        self.assertEqual(1, self.drivers[1].count_agents('host_agent'))
        self.assertEqual(1, self.drivers[1].count_agents('shard_agent'))
        self.assertEqual(1, self.drivers[1].count_agents('raage_agent'))
        self.assertEqual(1, self.drivers[1].count_agents('monitor_agent'))

        self.assertEqual(0,
                         self.drivers[0].count_agents('test_exportable_agent'))
        self.assertEqual(0, self.drivers[0].count_agents('test_child_agent'))
        self.assertEqual(2, self.drivers[0].count_agents('host_agent'))
        self.assertEqual(1, self.drivers[0].count_agents('shard_agent'))
        self.assertEqual(1, self.drivers[0].count_agents('raage_agent'))
        self.assertEqual(1, self.drivers[0].count_agents('monitor_agent'))

    @common.attr(save_journal=True, epu_in_new_cluster=50)
    @defer.inlineCallbacks
    def testMigrateAgentWhileNotHavingResource(self):
        yield self.migration.set_current('testing_site')
        shards = yield self.migration.get_structure()

        # we will migrate first shard (with only migratable agents)
        shard = recipient.IRecipient(self.host1).route
        to_migrate = first(x for x in shards if x.shard == shard)
        self.assertIsNot(None, to_migrate)

        migration = yield self.migration.prepare_shard_migration(to_migrate)

        # here we don't have enough epu in new cluster so first attempt to
        # spawn agent should fail. Cluster 1 should stabilize with exported
        # agent terminated and rest not touched. We should also get the alert
        # about the failure

        d = self.migration.apply_migration(migration)

        def condition():
            return len(self.alert.get_alerts()) > 0

        # now we will retry 3 times to find allocation before giving up
        yield self.wait_for(condition, 200)
        self.assertEqual(0,
                         self.drivers[0].count_agents('test_exportable_agent'))
        self.assertEqual(2,
                         self.drivers[0].count_agents('test_child_agent'))

        spawn_host = text_helper.format_block("""
        agency = spawn_agency()
        agency.disable_protocol('setup-monitoring', 'Task')
        agency.start_agent(descriptor_factory('host_agent'), hostdef=hostdef2)
        """)
        yield self.process(self.drivers[1], spawn_host)
        self.migration.spawn_next_agent()
        yield d
        yield self.wait_for_idle(10)

        self.assertEqual(1,
                         self.drivers[1].count_agents('test_exportable_agent'))
        self.assertEqual(2, self.drivers[1].count_agents('test_child_agent'))
        self.assertEqual(2, self.drivers[1].count_agents('host_agent'))
        self.assertEqual(1, self.drivers[1].count_agents('shard_agent'))
        self.assertEqual(1, self.drivers[1].count_agents('raage_agent'))
        self.assertEqual(1, self.drivers[1].count_agents('monitor_agent'))

        self.assertEqual(0,
                         self.drivers[0].count_agents('test_exportable_agent'))
        self.assertEqual(0, self.drivers[0].count_agents('test_child_agent'))
        self.assertEqual(2, self.drivers[0].count_agents('host_agent'))
        self.assertEqual(1, self.drivers[0].count_agents('shard_agent'))
        self.assertEqual(1, self.drivers[0].count_agents('raage_agent'))
        self.assertEqual(1, self.drivers[0].count_agents('monitor_agent'))
