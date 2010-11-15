import json

from twisted.internet import defer

from feat.agencies.emu import database
from feat.agents import document

from . import common


class TestDatabase(common.TestCase):

    def setUp(self):
        self.database = database.Database()

    @defer.inlineCallbacks
    def testSaveUnsavedDocument(self):
        content = self._generate_content('some text')
        resp = yield self.database.saveDoc(json.dumps(content))

        self.assertTrue('id' in resp)
        self.assertTrue('rev' in resp)

        self.assertEqual(1, len(self.database._documents))
        self.assertTrue(resp['id'] in self.database._documents)

        doc = self.database._documents[resp['id']]
        self.assertTrue(doc['text'] is not None)
        self.assertTrue(doc['_rev'] is not None)
        self.assertTrue(doc['_id'] is not None)
        self.assertEqual(resp['id'], doc['_id'])
        self.assertEqual(resp['rev'], doc['_rev'])

    @defer.inlineCallbacks
    def testUpdatingDocumentCorrectRevision(self):
        content1 = self._generate_content('some text')
        resp = yield self.database.saveDoc(json.dumps(content1))

        doc_id = resp['id']
        rev = resp['rev']

        content2 = self._generate_content('some new text')
        content2['_id'] = doc_id
        content2['_rev'] = rev

        resp2 = yield self.database.saveDoc(json.dumps(content2))

        self.assertEqual(resp2['id'], doc_id)
        self.assertNotEqual(resp2['rev'], rev)
        doc = self.database._documents[resp['id']]
        self.assertEqual("some new text", doc['text'])

    @defer.inlineCallbacks
    def testUpdatingDocumentWithoutRevisionOrIncorrect(self):
        content1 = self._generate_content('some text')
        resp = yield self.database.saveDoc(json.dumps(content1))

        doc_id = resp['id']

        content2 = self._generate_content('some new text')
        content2['_id'] = doc_id

        d = self.database.saveDoc(json.dumps(content2))
        self.assertFailure(d, RuntimeError)

        content2['_rev'] = 'incorrect revision'
        d = self.database.saveDoc(json.dumps(content2))
        self.assertFailure(d, RuntimeError)
        yield d

    def testNonStringDocument(self):
        content = dict()
        d = self.database.saveDoc(content)
        self.assertFailure(d, ValueError)

        return d

    @defer.inlineCallbacks
    def testPassingDifferentIdsInBodyInParam(self):
        content = dict()
        content['_id'] = 'id which loses'

        resp = yield self.database.saveDoc(json.dumps(content),
                                           'id which wins')
        self.assertEqual('id which wins', resp['id'])
        self.assertEqual(1, len(self.database._documents))
        self.assertTrue(resp['id'] in self.database._documents)

    @defer.inlineCallbacks
    def testPassingIdAsSecondParam(self):
        content = dict()

        resp = yield self.database.saveDoc(json.dumps(content),
                                           'id which wins')
        self.assertEqual('id which wins', resp['id'])
        self.assertEqual(1, len(self.database._documents))
        self.assertTrue(resp['id'] in self.database._documents)

    def _generate_content(self, text):
        return dict(text=text)


class TestDatabaseIntegration(common.TestCase):
    '''This testcase uses only external interface for sanity check.
    Idea is to later reuse the testcase for paisley.'''

    def setUp(self):
        self.database = database.Database()

    @defer.inlineCallbacks
    def testDeletingAndUpdating(self):
        content = dict()
        resp = yield self.database.saveDoc(json.dumps(content))
        id = resp['id']
        rev = resp['rev']

        resp2 = yield self.database.deleteDoc(id, rev)
        id2 = resp2['id']
        self.assertEqual(id, id2)
        rev2 = resp2['rev']
        self.assertNotEqual(rev2, rev)

        d = self.database.deleteDoc(id, rev)
        self.assertFailure(d, RuntimeError)
        yield d

        content['_rev'] = rev2
        content['_id'] = id
        resp3 = yield self.database.saveDoc(json.dumps(content))
        rev3 = resp3['rev']
        self.assertNotEqual(rev3, rev2)

    @defer.inlineCallbacks
    def testGettingDocumentUpdatingDeleting(self):
        id = 'test id'
        d = self.database.openDoc(id)
        self.assertFailure(d, RuntimeError)
        yield d

        content = {'_id': id, 'field': 'value'}
        resp = yield self.database.saveDoc(json.dumps(content))
        rev = resp['rev']
        self.assertEqual(id, resp['id'])

        fetched = yield self.database.openDoc(id)
        self.assertTrue(isinstance(fetched, dict))
        self.assertTrue('field' in fetched)
        self.assertEqual(rev, fetched['_rev'])

        del_resp = yield self.database.deleteDoc(id, rev)
        self.assertTrue(del_resp['ok'])

        d = self.database.openDoc(id)
        self.assertFailure(d, RuntimeError)
        yield d


@document.register
class DummyDocument(document.Document):

    document_type = "dummy"

    def __init__(self, field=None, **kwargs):
        document.Document.__init__(self, **kwargs)
        self.field = field

    def get_content(self):
        return dict(field=self.field)


class TestConnection(common.TestCase):

    def setUp(self):
        self.database = database.Database()
        self.connection = database.Connection(self.database)

    @defer.inlineCallbacks
    def testSavingDocument(self):
        doc = DummyDocument(field='something')
        doc = yield self.connection.save_document(doc)

        self.assertTrue(doc.doc_id is not None)
        self.assertTrue(doc.rev is not None)

        doc_in_database = self.database._documents[doc.doc_id]
        self.assertEqual('dummy', doc_in_database['document_type'])
        self.assertEqual(doc.rev, doc_in_database['_rev'])
        self.assertEqual(doc.doc_id, doc_in_database['_id'])

    @defer.inlineCallbacks
    def testSavingAndGettingTheDocument(self):
        doc = DummyDocument(field='something')
        doc = yield self.connection.save_document(doc)

        fetched_doc = yield self.connection.get_document(doc.doc_id)
        self.assertTrue(isinstance(fetched_doc, DummyDocument))
        self.assertEqual('something', fetched_doc.field)
        self.assertEqual(doc.rev, fetched_doc.rev)
        self.assertEqual(doc.doc_id, fetched_doc.doc_id)

    @defer.inlineCallbacks
    def testCreatingAndUpdatingTheDocument(self):
        doc = DummyDocument(field='something')
        doc = yield self.connection.save_document(doc)
        rev1 = doc.rev

        doc.field = 'something else'
        doc = yield self.connection.save_document(doc)
        rev2 = doc.rev

        self.assertNotEqual(rev1, rev2)

        fetched_doc = yield self.connection.get_document(doc.doc_id)
        self.assertEqual(fetched_doc.rev, rev2)
        self.assertEqual('something else', fetched_doc.field)

    @defer.inlineCallbacks
    def testReloadingDocument(self):
        doc = DummyDocument(field='something')
        doc = yield self.connection.save_document(doc)
        fetched_doc = yield self.connection.get_document(doc.doc_id)

        doc.field = 'something else'
        doc = yield self.connection.save_document(doc)

        self.assertEqual('something', fetched_doc.field)
        fetched_doc = yield self.connection.reload_document(fetched_doc)
        self.assertEqual('something else', fetched_doc.field)

    @defer.inlineCallbacks
    def testDeletingDocumentThanSavingAgain(self):
        doc = DummyDocument(field='something')
        doc = yield self.connection.save_document(doc)
        rev = doc.rev

        yield self.connection.delete_document(doc)

        self.assertNotEqual(doc.rev, rev)
        rev2 = doc.rev

        yield self.connection.save_document(doc)
        self.assertNotEqual(doc.rev, rev2)
