from twisted.internet import defer
from feat.agents.base import dbtools, document
from feat.test import common


@document.register
class SomeDocument(document.Document):

    document_type = 'spam'
    document.field('field1', u'default')


class TestCase(common.TestCase, common.AgencyTestHelper):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.AgencyTestHelper.setUp(self)
        self.db = self.agency._database
        self.connection = self.db.get_connection(self)

    @defer.inlineCallbacks
    def testDefiningDocument(self):
        dbtools.initial_data(SomeDocument)
        dbtools.initial_data(
            SomeDocument(doc_id=u'special_id', field1=u'special'))

        yield dbtools.push_initial_data(self.connection)
        self.assertEqual(2, len(self.db._documents))
        special = yield self.connection.get_document('special_id')
        self.assertIsInstance(special, SomeDocument)
        self.assertEqual('special', special.field1)
        ids = self.db._documents.keys()
        other_id = filter(lambda x: x != u'special_id', ids)[0]
        normal = yield self.connection.get_document(other_id)
        self.assertEqual('default', normal.field1)
