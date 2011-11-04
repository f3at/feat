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
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from zope.interface import implements

from feat.agencies.emu import database
from feat.agents.base import cache, document
from feat.common import journal, defer, log
from feat.test import common

from feat.agencies.interface import NotFoundError


class DummyAgent(journal.DummyRecorderNode, log.LogProxy, log.Logger):

    implements(cache.IDocumentChangeListener)

    def __init__(self, logger, db):
        log.LogProxy.__init__(self, logger)
        log.Logger.__init__(self, self)
        journal.DummyRecorderNode.__init__(self)

        # db connection
        self._db = db

        self.notifications = list()

    ### used by Cache ###

    def register_change_listener(self, doc_id, cb):
        self._db.changes_listener((doc_id, ), cb)

    def cancel_change_listener(self, doc_id):
        self._db.cancel_listener(doc_id)

    def get_document(self, doc_id):
        return self._db.get_document(doc_id)

    ### IDocumentChangeListner ###

    def on_document_change(self, doc):
        self.notifications.append(('change', doc.doc_id, doc))

    def on_document_deleted(self, doc_id):
        self.notifications.append(('delete', doc_id, None))

    ### used by the test case ###

    def len_notifications(self, num):

        def check():
            return len(self.notifications) == num

        return check


@document.register
class TestDocument(document.Document):

    document_type = 'test_document'
    document.field('field', 0)


class TestCache(common.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        db = database.Database()
        self._db = db.get_connection()
        self.agent = DummyAgent(self, db.get_connection())
        self.cache = cache.DocumentCache(self.agent, self.agent)

        yield self._db.save_document(TestDocument(doc_id=u'test'))
        yield self._db.save_document(TestDocument(doc_id=u'test2'))

    @defer.inlineCallbacks
    def testCache(self):
        doc = yield self.cache.add_document('test')
        self.assertIsInstance(doc, TestDocument)

        yield self._change_doc(doc)
        yield self.wait_for(self.agent.len_notifications(1), 1, 0.02)
        type_, doc_id, doc_ = self.agent.notifications.pop()
        self.assertEqual('change', type_)
        self.assertEqual(doc_id, doc.doc_id)
        self.assertEqual(doc, doc_)

        doc__ = self.cache.get_document(doc_id)
        self.assertEqual(doc_, doc__)

        # now test deleting
        doc = yield self.cache.add_document('test2')
        self.assertIsInstance(doc, TestDocument)

        doc = yield self._db.delete_document(doc)
        yield self.wait_for(self.agent.len_notifications(1), 1, 0.02)
        type_, doc_id, doc_ = self.agent.notifications.pop()
        self.assertEqual('delete', type_)
        self.assertEqual(doc_id, doc.doc_id)
        self.assertEqual(None, doc_)

        # recreate the document
        yield self._db.save_document(doc)
        yield self.wait_for(self.agent.len_notifications(1), 1, 0.02)
        type_, doc_id, doc_ = self.agent.notifications.pop()
        self.assertEqual('change', type_)
        self.assertEqual(doc_id, doc.doc_id)

        # forget it
        yield self.cache.forget_document(doc.doc_id)
        yield self._change_doc(doc)

        # change the other one to check that its notification comes first
        yield self._change_doc(doc__)
        yield self.wait_for(self.agent.len_notifications(1), 1, 0.02)
        type_, doc_id, doc_ = self.agent.notifications.pop()
        self.assertEqual('change', type_)
        self.assertEqual(doc_id, doc__.doc_id)

    def testGettingNonExistent(self):
        self.assertRaises(NotFoundError, self.cache.get_document,
                          'nonexistent2')
        self.assertRaises(NotFoundError, self.cache.get_document,
                          'nonexistent')

        d = self.cache.add_document("nonexistent")
        self.assertFailure(d, NotFoundError)
        return d

    def _change_doc(self, doc):
        doc.field += 1
        return self._db.save_document(doc)

    @defer.inlineCallbacks
    def tearDown(self):
        yield common.TestCase.tearDown(self)
