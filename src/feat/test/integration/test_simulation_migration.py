from feat.test.integration import common
from feat.common import defer, text_helper, first, fiber
from feat.agents.export import export_agent
from feat.agents.shard import shard_agent
from feat.agents.base import dbtools, descriptor, replay, agent, recipient
from feat.agents.common import export, start_agent

# this import is here to get the
from feat.test.integration.test_simulation_export import TestAgent


@agent.register('test_exportable_agent')
class ExportableAgent(TestAgent):

    migratability = export.Migratability.exportable

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


@common.attr(timescale=0.4)
class TestMigration(common.SimulationTest):

    def setUp(self):
        config = export_agent.ExportAgentConfiguration(
            doc_id = 'test-export-config',
            sitename = 'testing_site',
            version = 1,
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
        shard = recipient.IRecipient(self.host1).shard
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
        shard = recipient.IRecipient(self.host2).shard
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
