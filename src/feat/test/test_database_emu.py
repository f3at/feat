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
import json

from twisted.internet import defer

from feat.database import emu
from feat.database.interface import ConflictError, NotFoundError

from . import common


class TestDatabase(common.TestCase):

    def setUp(self):
        self.database = emu.Database()

    @defer.inlineCallbacks
    def testSaveUnsavedDocument(self):
        content = self._generate_content('some text')
        resp = yield self.database.save_doc(json.dumps(content))

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
        resp = yield self.database.save_doc(json.dumps(content1))

        doc_id = resp['id']
        rev = resp['rev']

        content2 = self._generate_content('some new text')
        content2['_id'] = doc_id
        content2['_rev'] = rev

        resp2 = yield self.database.save_doc(json.dumps(content2))

        self.assertEqual(resp2['id'], doc_id)
        self.assertNotEqual(resp2['rev'], rev)
        doc = self.database._documents[resp['id']]
        self.assertEqual("some new text", doc['text'])

    @defer.inlineCallbacks
    def testUpdatingDocumentWithoutRevisionOrIncorrect(self):
        content1 = self._generate_content('some text')
        resp = yield self.database.save_doc(json.dumps(content1))

        doc_id = resp['id']

        content2 = self._generate_content('some new text')
        content2['_id'] = doc_id

        d = self.database.save_doc(json.dumps(content2))
        self.assertFailure(d, ConflictError)

        content2['_rev'] = 'incorrect revision'
        d = self.database.save_doc(json.dumps(content2))
        self.assertFailure(d, ConflictError)
        yield d

    def testNonStringDocument(self):
        content = dict()
        d = self.database.save_doc(content)
        self.assertFailure(d, ValueError)

        return d

    @defer.inlineCallbacks
    def testPassingDifferentIdsInBodyInParam(self):
        content = dict()
        content['_id'] = 'id which loses'

        resp = yield self.database.save_doc(json.dumps(content),
                                           'id which wins')
        self.assertEqual('id which wins', resp['id'])
        self.assertEqual(1, len(self.database._documents))
        self.assertTrue(resp['id'] in self.database._documents)

    @defer.inlineCallbacks
    def testPassingIdAsSecondParam(self):
        content = dict()

        resp = yield self.database.save_doc(json.dumps(content),
                                           'id which wins')
        self.assertEqual('id which wins', resp['id'])
        self.assertEqual(1, len(self.database._documents))
        self.assertTrue(resp['id'] in self.database._documents)

    def _generate_content(self, text):
        return dict(text=text)


class TestDatabaseIntegration(common.TestCase):
    '''This testcase uses only external interface for sanity check.
    Idea is to later reuse the testcase for paisley.'''

    timeout = 3

    def setUp(self):
        self.database = emu.Database()

    @defer.inlineCallbacks
    def testDeletingAndUpdating(self):
        content = dict()
        resp = yield self.database.save_doc(json.dumps(content))
        id = resp['id']
        rev = resp['rev']

        resp2 = yield self.database.delete_doc(id, rev)
        id2 = resp2['id']
        self.assertEqual(id, id2)
        rev2 = resp2['rev']
        self.assertNotEqual(rev2, rev)

        d = self.database.delete_doc(id, rev)
        self.assertFailure(d, ConflictError)
        yield d

        content['_rev'] = rev2
        content['_id'] = id
        resp3 = yield self.database.save_doc(json.dumps(content))
        rev3 = resp3['rev']
        self.assertNotEqual(rev3, rev2)

    @defer.inlineCallbacks
    def testGettingDocumentUpdatingDeleting(self):
        id = 'test id'
        d = self.database.open_doc(id)
        self.assertFailure(d, NotFoundError)
        yield d

        content = {'_id': id, 'field': 'value'}
        resp = yield self.database.save_doc(json.dumps(content))
        rev = resp['rev']
        self.assertEqual(id, resp['id'])

        fetched = yield self.database.open_doc(id)
        self.assertTrue(isinstance(fetched, dict))
        self.assertTrue('field' in fetched)
        self.assertEqual(rev, fetched['_rev'])

        del_resp = yield self.database.delete_doc(id, rev)
        self.assertTrue(del_resp['ok'])

        d = self.database.open_doc(id)
        self.assertFailure(d, NotFoundError)
        yield d

    @defer.inlineCallbacks
    def testListeningOnChanges(self):
        self.calls = list()

        d = self.cb_after(None, self, 'change_cb')
        listener_id = yield self.database.listen_changes(
            ('someid', ), self.change_cb)
        self.assertIsInstance(listener_id, (str, unicode, ))
        self.assertEqual(0, len(self.calls))
        resp = yield self.database.save_doc(self._gen_doc('someid'))
        yield d
        self.assertEqual(1, len(self.calls))
        doc_id, rev, deleted = self.calls[0]
        self.assertEqual(doc_id, resp['id'])
        self.assertEqual(rev, resp['rev'])
        self.assertFalse(deleted)

        yield self.database.cancel_listener(listener_id)
        yield self.database.delete_doc(doc_id, rev)
        self.assertEqual(1, len(self.calls))

    def change_cb(self, doc_id, rev, deleted):
        self.calls.append((doc_id, rev, deleted))

    def _gen_doc(self, doc_id):
        return json.dumps({'_id': doc_id})
