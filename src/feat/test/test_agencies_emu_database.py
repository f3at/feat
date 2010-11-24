import json

from twisted.internet import defer

from feat.agencies.emu import database
from feat.agents import document
from feat.agencies.emu.interface import ConflictError, NotFoundError

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
        self.assertFailure(d, ConflictError)

        content2['_rev'] = 'incorrect revision'
        d = self.database.saveDoc(json.dumps(content2))
        self.assertFailure(d, ConflictError)
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
        self.assertFailure(d, ConflictError)
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
        self.assertFailure(d, NotFoundError)
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
        self.assertFailure(d, NotFoundError)
        yield d
