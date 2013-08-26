from feat.common.serialization import base
from feat.common import defer
from feat.database import client, document, common as dcommon, emu, migration
from feat.test import common


class Inside(document.VersionedFormatable):

    type_name = 'dummy'
    version = 2

    document.field("field", None)
    document.field("nested", None)

    @staticmethod
    def upgrade_to_2(snapshot):
        snapshot['field'] = 'migrated'
        return snapshot


class MigratableDoc(document.VersionedDocument):

    version = 3
    type_name = 'migratable-document-test'

    document.field('field', None)
    document.field('nested', None)


class Migration(migration.Migration):

    source_ver = 2
    target_ver = 3
    type_name = MigratableDoc.type_name

    def synchronous_hook(self, snapshot):
        snapshot['field'] = 'migrated'
        return snapshot, dict(some_context=True)

    def asynchronous_hook(self, connection, document, context):
        document.context = context


class UnserializingAndMigrationgTest(common.TestCase):

    def setUp(self):
        self.registry = base.Registry()
        self.registry.register(Inside)
        self.registry.register(MigratableDoc)

        migration.get_registry().register(Migration())

        self.db = emu.Database()
        self.unserializer = dcommon.CouchdbUnserializer(registry=self.registry)
        self.client = client.Connection(self.db, self.unserializer)

    @defer.inlineCallbacks
    def testNestedObjectInAList(self):
        nested = {'.type': 'dummy',
                'field': 'not migrated',
                '.version': 1}
        data = {'.type': 'migratable-document-test',
                '_id': "test-doc",
                'field': 'not migrated',
                '.version': 2,
                'nested': [1, nested]}
        doc = yield self.client.unserialize_document(data)
        self.assertIsInstance(doc, MigratableDoc)
        self.assertEqual(1, len(self.db._documents))

        self.assertEqual('migrated', doc.field)
        self.assertIsInstance(doc.nested, list)
        self.assertEqual(1, doc.nested[0])
        self.assertIsInstance(doc.nested[1], Inside)
        self.assertEqual('migrated', doc.nested[1].field)
        self.assertTrue(doc.has_migrated)
        self.assertEqual({'some_context': True}, doc.context)

        fetched = yield self.client.get_document("test-doc")
        self.assertEqual(3, fetched.version)
        self.assertIsInstance(fetched, MigratableDoc)
