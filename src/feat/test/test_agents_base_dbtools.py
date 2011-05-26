from twisted.internet import defer
from feat.agents.base import dbtools, document
from feat.test import common
from feat.test.integration.common import SimulationTest


@document.register
class SomeDocument(document.Document):

    document_type = 'spam'
    document.field('field1', u'default')


class TestCase(common.TestCase, common.AgencyTestHelper):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.AgencyTestHelper.setUp(self)
        self.db = self.agency._database
        self.connection = self.db.get_connection()
        dbtools._documents = []

    @defer.inlineCallbacks
    def testDefiningDocument(self):
        dbtools.initial_data(SomeDocument)
        dbtools.initial_data(
            SomeDocument(doc_id=u'special_id', field1=u'special'))

        yield dbtools.push_initial_data(self.connection)
        # 3 = 2 (registered documents) + 1 (design document)
        self.assertEqual(3, len(self.db._documents))
        special = yield self.connection.get_document('special_id')
        self.assertIsInstance(special, SomeDocument)
        self.assertEqual('special', special.field1)
        ids = self.db._documents.keys()
        other_id = filter(lambda x: x not in ('special_id', "_design/feat"),
                          ids)[0]
        normal = yield self.connection.get_document(other_id)
        self.assertEqual('default', normal.field1)

    def testRevertingDocuments(self):
        old = dbtools.get_current_initials()
        dbtools.initial_data(SomeDocument)
        current = dbtools.get_current_initials()
        self.assertEqual(len(old) + 1, len(current))
        dbtools.reset_documents(old)
        current = dbtools.get_current_initials()
        self.assertEqual(len(old), len(current))


class IntegrationWithSimulation(SimulationTest):

    def setUp(self):
        dbtools.initial_data(SomeDocument)
        return SimulationTest.setUp(self)

    def testItWorks(self):
        pass

    @defer.inlineCallbacks
    def tearDown(self):
        yield SimulationTest.tearDown(self)
        current = dbtools.get_current_initials()
        self.assertFalse(isinstance(current[-1], SomeDocument))
