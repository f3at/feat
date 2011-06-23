import operator
import uuid

from feat.common import defer
from feat.test import common
from feat.agents.export import export_agent
from feat.agents.common import export


class CheckinListTest(common.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        self.migration = export_agent.Migration()
        self.list = self.migration.checkins

    def reset(self):
        self.migration.reset()
        self.migration.checkins = self.list

    def generate_test_shard(self):
        '''
        Entries for shard with 3 hosts, structural agents and the one simple
        flt flow.
        Host 1 runs all the structural agents.
        Host 2 runs signal agent, manager and one worker.
        Host 3 runs one worker and alert agent.
        '''
        hosts = map(lambda x: self.host_entry(), range(3))
        shard = self.shard_entry()
        raage = self.raage_entry()
        monitor = self.monitor_entry()
        alert = self.alert_entry()
        entries = self.flow_entries()

        hosts[0].add_dependency(shard)
        hosts[0].add_dependency(raage)
        hosts[0].add_dependency(monitor)
        hosts[1].add_dependency(entries[0])
        hosts[1].add_dependency(entries[1])
        hosts[1].add_dependency(entries[2])
        hosts[2].add_dependency(entries[3])
        hosts[2].add_dependency(alert)

        all_entries = entries + hosts + [shard, raage, monitor, alert]
        for e in all_entries:
            self.list.add_entry(e)
        signal, manager, worker1, worker2 = entries
        return (hosts, shard, monitor, raage, alert,
                signal, manager, worker1, worker2)

    def testRecursiveDependencyFirstStep(self):
        (hosts, shard, monitor, raage, alert,
         signal, manager, worker1, worker2) = self.generate_test_shard()

        monitor.add_dependency(hosts[0])
        self.assertRaises(export_agent.RecursiveDependency,
                          self.list.generate_migration, hosts[0].agent_id)
        self.migration.analyze(hosts[0])
        self.assertFalse(self.migration.is_completable())
        self.assertIsInstance(self.migration.problem,
                              export_agent.RecursiveDependency)

    def testRecursiveDependencyTwoSteps(self):
        (hosts, shard, monitor, raage, alert,
         signal, manager, worker1, worker2) = self.generate_test_shard()

        monitor.add_dependency(alert)
        # this is stil fine
        migration = self.list.generate_migration(hosts[0].agent_id)
        self.assertEqual(5, len(migration))
        alert.add_dependency(hosts[0])
        # now we have a dependency cycle
        self.assertRaises(export_agent.RecursiveDependency,
                          self.list.generate_migration, hosts[0].agent_id)

    def testUnmigratableStuff(self):
        (hosts, shard, monitor, raage, alert,
         signal, manager, worker1, worker2) = self.generate_test_shard()

        def assert_on_partial_host0(migration):
            self.assertIsInstance(migration, list)
            self.assertEqual(3, len(migration))
            ids = list()
            for step in migration[0:3]:
                self.assertEqual(step.strategy,
                                 export.Migratability.locally)
                ids.append(step.agent_id)
            self.assertEqual(set(ids),
                             self.extract_ids([shard, raage, monitor]))

        def assert_on_partial_host1(migration):
            self.assertEqual(4, len(migration))

            step = migration[0]
            self.assertEqual(signal.agent_id, step.agent_id)
            self.assertEqual(step.strategy,
                             export.Migratability.exportable)
            ids = list()
            for step in migration[1:4]:
                self.assertEqual(step.strategy,
                                 export.Migratability.shutdown)
                ids.append(step.agent_id)
            self.assertEqual(set(ids),
                             self.extract_ids([worker1, worker2, manager]))

        dns = self.dns_entry()
        hosts[0].add_dependency(dns)

        # host 0 depends on agent, which we don't have on checkin list
        ex = self.assertRaises(export_agent.NotCheckedIn,
                               self.list.generate_migration,
                               hosts[0].agent_id)
        self.migration.analyze(hosts[0])
        self.assertFalse(self.migration.is_completable())
        assert_on_partial_host0(self.migration.steps)
        self.reset()

        # host 0 cannot be migrated as it runs DNS agent who need to live as
        # long as the cluster
        self.list.add_entry(dns)
        ex = self.assertRaises(export_agent.NotMigratable,
                          self.list.generate_migration,
                          hosts[0].agent_id)
        self.migration.analyze(hosts[0])
        assert_on_partial_host0(self.migration.steps)
        self.assertFalse(self.migration.is_completable())

        self.reset()
        # now test with migratable agents
        hosts[1].add_dependency(dns)
        ex = self.assertRaises(export_agent.NotMigratable,
                          self.list.generate_migration,
                          hosts[1].agent_id)
        self.migration.analyze(hosts[1])
        assert_on_partial_host1(self.migration.steps)
        self.assertFalse(self.migration.is_completable())

    def testGeneratingMigration(self):
        (hosts, shard, monitor, raage, alert,
         signal, manager, worker1, worker2) = self.generate_test_shard()

        # Test migration Host 0
        self.migration.analyze(hosts[0])
        self.assertEqual(4, len(self.migration.steps))
        ids = list()
        for step in self.migration.steps[0:3]:
            self.assertEqual(step.strategy, export.Migratability.locally)
            ids.append(step.agent_id)
        self.assertEqual(set(ids), self.extract_ids([shard, raage, monitor]))

        step = self.migration.steps[3]
        self.assertEqual(step.agent_id, hosts[0].agent_id)
        self.assertEqual(step.strategy, export.Migratability.host)
        kill_list = self.migration.get_kill_list()
        self.assertIn(hosts[0].shard, kill_list)
        self.assertEqual([hosts[0].agent_id], kill_list[hosts[0].shard])
        self.migration.remove_local_migrations(hosts[0].shard)
        self.assertEqual(1, len(self.migration.steps))
        self.assertEqual(export.Migratability.host,
                         self.migration.steps[0].strategy)

        # Test migration Host 1
        self.reset()
        self.migration.analyze(hosts[1])
        self.assertTrue(self.migration.is_completable())
        self.assertEqual(5, len(self.migration.steps))

        step = self.migration.steps[0]
        self.assertEqual(signal.agent_id, step.agent_id)
        self.assertEqual(step.strategy,
                         export.Migratability.exportable)
        ids = list()
        for step in self.migration.steps[1:4]:
            self.assertEqual(step.strategy,
                             export.Migratability.shutdown)
            ids.append(step.agent_id)

        self.assertEqual(set(ids),
                         self.extract_ids([worker1, worker2, manager]))
        step = self.migration.steps[4]
        self.assertEqual(step.agent_id, hosts[1].agent_id)
        self.assertEqual(step.strategy, export.Migratability.host)

        # Test migration Host 2
        self.reset()
        self.migration.analyze(hosts[2])
        self.assertEqual(6, len(self.migration.steps))
        step = self.migration.steps[0]
        self.assertEqual(alert.agent_id, step.agent_id)
        self.assertEqual(step.strategy, export.Migratability.globally)
        step = self.migration.steps[1]
        self.assertEqual(signal.agent_id, step.agent_id)
        self.assertEqual(step.strategy, export.Migratability.exportable)
        ids = list()
        for step in self.migration.steps[2:5]:
            self.assertEqual(step.strategy,
                             export.Migratability.shutdown)
            ids.append(step.agent_id)
        self.assertEqual(set(ids),
                         self.extract_ids([worker1, worker2, manager]))
        step = self.migration.steps[5]
        self.assertEqual(step.agent_id, hosts[2].agent_id)
        self.assertEqual(step.strategy, export.Migratability.host)

    def gen_entry(self, **params):
        return export.CheckinEntry(**params)

    def gen_id(self):
        return str(uuid.uuid1())

    def host_entry(self):
        agent_id = self.gen_id()
        return self.gen_entry(agent_id=agent_id,
                              agent_type='host_agent',
                              shard='shard',
                              migratability=export.Migratability.host)

    def shard_entry(self):
        agent_id = self.gen_id()
        return self.gen_entry(agent_id=agent_id,
                              agent_type='shard_agent',
                              shard='shard',
                              migratability=export.Migratability.locally)

    def raage_entry(self):
        agent_id = self.gen_id()
        return self.gen_entry(agent_id=agent_id,
                              agent_type='raage_agent',
                              shard='shard',
                              migratability=export.Migratability.locally)

    def monitor_entry(self):
        agent_id = self.gen_id()
        return self.gen_entry(agent_id=agent_id,
                              agent_type='monitor_agent',
                              shard='shard',
                              migratability=export.Migratability.locally)

    def alert_entry(self):
        agent_id = self.gen_id()
        return self.gen_entry(agent_id=agent_id,
                              agent_type='alert_agent',
                              shard='shard',
                              migratability=export.Migratability.globally)

    def dns_entry(self):
        agent_id = self.gen_id()
        return self.gen_entry(agent_id=agent_id,
                              agent_type='dns_agent',
                              shard='shard',
                        migratability=export.Migratability.not_migratable)

    def flow_entries(self):
        resp = list()
        signal_id = self.gen_id()
        resp.append(
            self.gen_entry(agent_id=signal_id,
                           agent_type='signal_agent',
                           shard='shard',
                           migratability=export.Migratability.exportable))
        manager_id = self.gen_id()
        resp.append(
            self.gen_entry(agent_id=manager_id,
                           agent_type='manager_agent',
                           shard='shard',
                        migratability=export.Migratability.shutdown,
                           dependencies=[signal_id]))
        for _ in range(2):
            resp.append(
                self.gen_entry(agent_id=self.gen_id(),
                               agent_type='worker_agent',
                               shard='shard',
                        migratability=export.Migratability.shutdown,
                           dependencies=[manager_id]))
        return resp

    def extract_ids(self, entries):
        return set(map(operator.attrgetter('agent_id'), entries))
