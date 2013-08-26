from feat.test import common
from feat.database import migration, document

from feat.database.interface import NotMigratable
from feat.interface.serialization import IVersionAdapter


TYPE_NAME = 'nonexisting-type'


class A(document.VersionedDocument):

    type_name = TYPE_NAME
    version = 6

    document.field('field1', 0)


class FakeMigration(migration.Migration):

    type_name = TYPE_NAME

    def synchronous_hook(self, snapshot):
        return snapshot, dict(source=self.source_ver, target=self.target_ver)


class TestVersionAdapter(common.TestCase):

    def setUp(self):
        self.registry = r = migration.get_registry()
        r.register(FakeMigration(source_ver=1, target_ver=3))
        r.register(FakeMigration(source_ver=2, target_ver=3))
        r.register(FakeMigration(source_ver=3, target_ver=4))
        r.register(FakeMigration(source_ver=3, target_ver=5))
        r.register(FakeMigration(source_ver=5, target_ver=6))

    def testPreparePlan(self):
        plan = A.plan_migration(1, 3)
        self.assertIsInstance(plan, list)
        self.assertEqual(1, len(plan))

        plan = A.plan_migration(1, 6)
        self.assertIsInstance(plan, list)
        self.assertEqual(3, len(plan))
        self.assertEqual(1, plan[0].source_ver)
        self.assertEqual(3, plan[0].target_ver)
        self.assertEqual(3, plan[1].source_ver)
        self.assertEqual(5, plan[1].target_ver)
        self.assertEqual(5, plan[2].source_ver)
        self.assertEqual(6, plan[2].target_ver)

        self.assertRaises(NotMigratable, A.plan_migration, 1, 2)

    def testAdaptation(self):
        self.assertTrue(IVersionAdapter.providedBy(A))

    def testTransform(self):
        snapshot = {'field1': 10}
        res = A.adapt_version(snapshot, 1, 6)
        ver = lambda s, t: self.registry.lookup((TYPE_NAME, s, t))
        dic = lambda s, t: dict(source=s, target=t)
        ex = {
            'field1': 10,
            '_has_migrated': True,
            '_asynchronous_actions': [
                (ver(1, 3), dic(1, 3)),
                (ver(3, 5), dic(3, 5)),
                (ver(5, 6), dic(5, 6))]}
        self.assertEqual(ex, res)

        a = A.restore(dict(ex))
        self.assertTrue(a.has_migrated)
        self.assertEqual(ex['_asynchronous_actions'],
                         a.get_asynchronous_actions())
