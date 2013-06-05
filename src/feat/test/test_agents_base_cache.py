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
import copy
import uuid

from zope.interface import implements

from feat.database import emu as database, document, view
from feat.agents.base import cache, descriptor
from feat.common import journal, defer, log, fiber, time, serialization
from feat.test import common

from feat.database.interface import NotFoundError


class Descriptor(descriptor.Descriptor):

    descriptor.field('pending_updates', list())


class DummyAgent(journal.DummyRecorderNode, log.LogProxy, log.Logger):

    implements(cache.IDocumentChangeListener)

    def __init__(self, logger, db):
        log.LogProxy.__init__(self, logger)
        log.Logger.__init__(self, self)
        journal.DummyRecorderNode.__init__(self)

        # db connection
        self._db = db
        self._descriptor = Descriptor()

        self.notifications = list()

        # call_id -> DelayedCall
        self._delayed_calls = dict()

    ### used by Cache ###

    def register_change_listener(self, doc_id, cb, **kwargs):
        if isinstance(doc_id, (str, unicode)):
            doc_id = (doc_id, )
        self._db.changes_listener(doc_id, cb, **kwargs)

    def cancel_change_listener(self, doc_id):
        self._db.cancel_listener(doc_id)

    def get_document(self, doc_id):
        return fiber.wrap_defer(self._db.get_document, doc_id)

    def save_document(self, document):
        return fiber.wrap_defer(self._db.save_document, document)

    def delete_document(self, document):
        return fiber.wrap_defer(self._db.delete_document, document)

    def query_view(self, factory, **kwargs):
        return fiber.wrap_defer(self._db.query_view, factory, **kwargs)

    ### used by DescriptorQueueHolder ###

    def get_descriptor(self):
        return self._descriptor

    def update_descriptor(self, _method, *args, **kwargs):
        f = fiber.succeed()
        f.add_callback(fiber.drop_param,
                      _method, self._descriptor, *args, **kwargs)
        return f

    ### used by PersistentUpdater ###

    def call_later(self, _time, _method, *args, **kwargs):
        id = str(uuid.uuid1())
        call = time.call_later(_time, _method, *args, **kwargs)
        self._delayed_calls[id] = call
        return id

    def call_next(self, _method, *args, **kwargs):
        self.call_later(0, _method, *args, **kwargs)

    def cancel_delayed_call(self, call_id):
        call = self._delayed_calls.pop(call_id)
        call.cancel()

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

    def example_operation(self, document, result=None):
        if isinstance(result, int):
            document.field = result
            return document
        elif result == 'delete':
            raise cache.DeleteDocument()
        elif result == 'resign':
            raise cache.ResignFromModifying()
        else:
            raise AttributeError('wtf is %s?' % (result, ))

    def teardown(self):
        for call in self._delayed_calls.values():
            if call.active():
                call.cancel()


@serialization.register
class TestDocument(document.Document):

    type_name = 'test_document'
    document.field('field', 0)
    document.field('zone', None, keep_deleted=True)


@serialization.register
class TestView(view.FormatableView):

    name = 'test_view'

    def map(doc):
        if doc.get('.type') == 'test_document':
            zone = doc.get('zone')
            yield zone, dict(doc_id=doc.get('_id'))

    def filter(doc, request):
        zone = request['query'].get('zone')
        return doc.get('.type') == 'test_document' and \
               (zone is None or zone == doc.get('zone'))

    view.field('doc_id', None)


class TestCacheWorkingWithViewFilter(common.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        db = database.Database()
        self._db = db.get_connection()

        design_doc = view.DesignDocument.generate_from_views((TestView, ))[0]
        yield self._db.save_document(design_doc)

        self.agent = DummyAgent(self, db.get_connection())
        filter_params = dict(zone='test_zone')
        self.cache = cache.DocumentCache(
            self.agent, self.agent, TestView, filter_params)

        yield self._db.save_document(
            TestDocument(doc_id=u'test', zone=u'test_zone'))
        yield self._db.save_document(
            TestDocument(doc_id=u'test2', zone=u'other_zone'))

    @defer.inlineCallbacks
    def testItsWorking(self):
        doc_ids = yield self.cache.load_view(key='test_zone')
        self.assertEqual(['test'], doc_ids)
        doc = self.cache.get_document('test')
        self.assertIsInstance(doc, TestDocument)

        self.assertEqual(0, len(self.agent.notifications))

        doc_ = yield self._db.save_document(
            TestDocument(doc_id=u'test3', zone=u'test_zone'))
        yield self.wait_for(self.agent.len_notifications(1), 1, 0.02)
        type_, doc_id, doc = self.agent.notifications.pop()
        self.assertEqual('change', type_)
        self.assertEqual(doc_, doc)

        self._db.delete_document(doc_)
        yield self.wait_for(self.agent.len_notifications(1), 1, 0.02)
        self.assertRaises(NotFoundError, self.cache.get_document, doc_.doc_id)
        self.assertNotIn(doc_.doc_id, self.cache.get_document_ids())


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

        doc = yield self._change_doc(doc)
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

        yield self._db.delete_document(doc)
        yield self.wait_for(self.agent.len_notifications(1), 1, 0.02)
        type_, doc_id, doc_ = self.agent.notifications.pop()
        self.assertEqual('delete', type_)
        self.assertEqual(doc_id, doc.doc_id)
        self.assertEqual(None, doc_)

        # recreate the document
        doc = yield self._db.save_document(doc)
        yield self.wait_for(self.agent.len_notifications(1), 1, 0.02)
        type_, doc_id, doc_ = self.agent.notifications.pop()
        self.assertEqual('change', type_)
        self.assertEqual(doc_id, doc.doc_id)

        # forget it
        yield self.cache.forget_document(doc.doc_id)
        doc = yield self._change_doc(doc)

        # change the other one to check that its notification comes first
        doc = yield self._change_doc(doc__)
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
        doc = copy.deepcopy(doc)
        doc.field += 1
        return self._db.save_document(doc)

    @defer.inlineCallbacks
    def tearDown(self):
        yield common.TestCase.tearDown(self)


class TestDescriptorQueueHolder(common.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)

        db = database.Database()
        self._db = db.get_connection()
        self.agent = DummyAgent(self, db.get_connection())

        self.holder = cache.DescriptorQueueHolder(
            self.agent, 'pending_updates')

    @defer.inlineCallbacks
    def testEnqueuAndNext(self):
        yield self.holder.enqueue('some_id', 'example_operation', 'test_doc',
                                  (3, ), dict())
        yield self.holder.enqueue('some_id2', 'example_operation',
                                  'test_doc', (2, ), dict())
        yield self.holder.enqueue('some_id3', 'example_operation',
                                  'test_doc', (1, ), dict())

        desc = self.agent.get_descriptor()
        self.assertEqual(3, len(desc.pending_updates))

        o_id, doc_id, args, kwargs, item_id = yield self.holder.next()
        self.assertEqual('test_doc', doc_id)
        self.assertEqual('some_id', item_id)

        o_id, doc_id, args, kwargs, item_id = yield self.holder.next()
        self.assertEqual('test_doc', doc_id)
        self.assertEqual('some_id2', item_id)

        o_id, doc_id, args, kwargs, item_id = yield self.holder.next()
        self.assertEqual('test_doc', doc_id)
        self.assertEqual('some_id3', item_id)
        self.assertEqual((1, ), args)

        d = self.holder.next()
        self.assertFailure(d, StopIteration)
        yield d

        doc = self._db.save_document(TestDocument(doc_id=u'test_doc'))
        doc_ = self.holder.perform(o_id, doc, args, kwargs)
        self.assertEqual(1, doc_.field)

        yield self.holder.on_confirm('some_id3')
        self.assertNotIn('some_id3', desc.pending_updates)
        self.assertEqual(2, len(desc.pending_updates))

        yield self.holder.on_confirm('some_id')
        self.assertNotIn('some_id', desc.pending_updates)
        self.assertEqual(1, len(desc.pending_updates))

        yield self.holder.on_confirm('some_id2')
        self.assertEqual(0, len(desc.pending_updates))


class TestPersistentUpdater(common.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        db = database.Database()
        self._db = db.get_connection()

        design_doc = view.DesignDocument.generate_from_views((TestView, ))[0]
        yield self._db.save_document(design_doc)

        self.agent = DummyAgent(self, db.get_connection())
        filter_params = dict(zone='test_zone')
        self.cache = cache.DocumentCache(
            self.agent, self.agent, TestView, filter_params)

        self.holder = cache.DescriptorQueueHolder(
            self.agent, 'pending_updates')
        self.updater = cache.PersistentUpdater(
            self.holder, self.cache, self.agent)

        yield self._db.save_document(
            TestDocument(doc_id=u'test', zone=u'test_zone'))
        yield self._db.save_document(
            TestDocument(doc_id=u'test2', zone=u'other_zone'))
        yield self.cache.load_view(key='test_zone')

    @defer.inlineCallbacks
    def testSimpleUpdate(self):
        doc = yield self._db.get_document('test')
        doc_ = yield self.updater.update(doc.doc_id, 'example_operation', 3)
        self.assertEqual(doc_.doc_id, doc.doc_id)
        self.assertNotEqual(doc_.rev, doc.rev)

    @defer.inlineCallbacks
    def testDeleting(self):
        doc = yield self._db.get_document('test')
        doc_ = yield self.updater.update(doc.doc_id, 'example_operation',
                                         'delete')
        self.assertEqual(doc_.doc_id, doc.doc_id)
        self.assertNotEqual(doc_.rev, doc.rev)
        d = self._db.get_document('test')
        self.assertFailure(d, NotFoundError)
        yield d
        self.assertRaises(NotFoundError, self.cache.get_document, 'test')

    @defer.inlineCallbacks
    def testResign(self):
        doc = yield self._db.get_document('test')
        doc_ = yield self.updater.update(doc.doc_id, 'example_operation',
                                         'resign')
        self.assertEqual(doc_.doc_id, doc.doc_id)
        self.assertEqual(doc_.rev, doc.rev)

    @defer.inlineCallbacks
    def testUpdateWithConflict(self):
        doc = yield self.cache.get_document('test')
        doc.rev = 'bad revision' # hack. touching rev stored in internal state
                                 # state of the cache, just to provke conflict
        doc_ = yield self.updater.update(doc.doc_id, 'example_operation', 3)
        self.assertEqual(doc_.doc_id, doc.doc_id)
        self.assertNotEqual(doc_.rev, doc.rev)

    @defer.inlineCallbacks
    def tearDown(self):
        self.agent.teardown()
        yield common.TestCase.tearDown(self)
