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

from twisted.internet import defer
from twisted.trial.unittest import SkipTest

try:
    from feat.agencies.net import database
except ImportError as e:
    database = None
    import_error = e

from feat.agencies.emu import database as emu_database
from feat.agents.base import document, view
from feat.process import couchdb
from feat.process.base import DependencyError
from feat.common import serialization
from feat.agencies.common import ConnectionState

from . import common
from feat.test.common import attr, Mock

from feat.agencies.interface import *


@document.register
class DummyDocument(document.Document):

    document_type = 'dummy'

    document.field('field', None)
    document.field('value', 0)


@document.register
class ViewDocument(document.Document):

    document_type = 'view-dummy'

    document.field('field', None)
    document.field('value', 0)


class FilteringView(view.BaseView):

    name = 'filter_view'

    def filter(doc, request):
        return doc.get('.type', None) == 'view-dummy' and\
               doc['field'] == request['query']['field']


class SummingView(view.FormatableView):

    name = 'some_view'
    use_reduce = True

    view.field('value', None)

    def map(doc):
        if doc['.type'] == 'dummy':
            yield None, {"value": doc['value']}

    def reduce(keys, values):
        value = 0
        for row in values:
            value += row['value']
        return value


class CountingView(view.BaseView):

    name = 'counting_view'
    use_reduce = True

    def map(doc):
        if doc['.type'] == 'dummy':
            yield doc['_id'], 1

    reduce = "_count"


class TestCase(object):

    @defer.inlineCallbacks
    def testSavingDeletedDoc(self):
        doc1 = DummyDocument(field=u'something')
        doc1 = yield self.connection.save_document(doc1)
        fetched_doc1 = yield self.connection.get_document(doc1.doc_id)
        self.assertEqual(u'something', fetched_doc1.field)
        yield self.connection.delete_document(fetched_doc1)
        yield self.asyncErrback(NotFoundError,
                                 self.connection.get_document, doc1.doc_id)
        doc2 = DummyDocument(field=u'someone')
        doc2.doc_id = doc1.doc_id
        doc2 = yield self.connection.save_document(doc2)
        self.assertEqual(doc1.doc_id, doc2.doc_id)
        fetched_doc2 = yield self.connection.get_document(doc1.doc_id)
        self.assertEqual(u'someone', fetched_doc2.field)

    @defer.inlineCallbacks
    def testQueryingViews(self):
        # create design document
        views = (SummingView, CountingView, )
        design_doc = view.DesignDocument.generate_from_views(views)
        yield self.connection.save_document(design_doc)

        # check formatable view returning empty list
        resp = yield self.connection.query_view(SummingView, reduce=False)
        self.assertIsInstance(resp, list)
        self.assertFalse(resp)

        # check reducing view returning empty result
        resp = yield self.connection.query_view(CountingView)
        self.assertFalse(resp)

        # safe first document
        doc1 = yield self.connection.save_document(DummyDocument(value=2))

        # check summing views
        resp = yield self.connection.query_view(SummingView, reduce=False)
        self.assertIsInstance(resp, list)
        self.assertEqual(1, len(resp))
        self.assertIsInstance(resp[0], SummingView)
        self.assertEqual(2, resp[0].value)

        # now check counting view
        resp = yield self.connection.query_view(CountingView)
        self.assertEqual(1, resp[0])

        # use summing view with reduce
        resp = yield self.connection.query_view(SummingView)
        self.assertEqual([2], resp)

        # save second document
        doc2 = yield self.connection.save_document(DummyDocument(value=3))

        # check SummingView without reduce
        resp = yield self.connection.query_view(SummingView, reduce=False)
        self.assertIsInstance(resp, list)
        self.assertEqual(2, len(resp))
        self.assertIsInstance(resp[0], SummingView)
        self.assertIn(resp[0].value, (2, 3, ))
        self.assertIsInstance(resp[1], SummingView)
        self.assertIn(resp[1].value, (2, 3, ))

        # check that reduce works as well
        resp = yield self.connection.query_view(SummingView)
        self.assertEqual([5], resp)

        # finnally check the counting view works as expected
        resp = yield self.connection.query_view(CountingView)
        self.assertEqual(2, resp[0])

        # change value of first doc and check that sum changed
        doc1.value = 10
        doc1 = yield self.connection.save_document(doc1)
        resp = yield self.connection.query_view(SummingView)
        self.assertEqual([13], resp)

        # now delete it
        yield self.connection.delete_document(doc1)
        resp = yield self.connection.query_view(SummingView)
        self.assertEqual([3], resp)

    @defer.inlineCallbacks
    def testSavingAndGettingTheDocument(self):
        doc = DummyDocument(field=u'something')
        doc = yield self.connection.save_document(doc)

        fetched_doc = yield self.connection.get_document(doc.doc_id)
        self.assertTrue(isinstance(fetched_doc, DummyDocument))
        self.assertEqual(u'something', fetched_doc.field)
        self.assertEqual(doc.rev, fetched_doc.rev)
        self.assertEqual(doc.doc_id, fetched_doc.doc_id)

    @defer.inlineCallbacks
    def testCreatingAndUpdatingTheDocument(self):
        doc = DummyDocument(field=u'something')
        doc = yield self.connection.save_document(doc)
        rev1 = doc.rev

        doc.field = u'something else'
        doc = yield self.connection.save_document(doc)
        rev2 = doc.rev

        self.assertNotEqual(rev1, rev2)

        fetched_doc = yield self.connection.get_document(doc.doc_id)
        self.assertEqual(fetched_doc.rev, rev2)
        self.assertEqual('something else', fetched_doc.field)

    @defer.inlineCallbacks
    def testReloadingDocument(self):
        doc = DummyDocument(field=u'something')
        doc = yield self.connection.save_document(doc)
        fetched_doc = yield self.connection.get_document(doc.doc_id)

        doc.field = u'something else'
        doc = yield self.connection.save_document(doc)

        self.assertEqual(u'something', fetched_doc.field)
        fetched_doc = yield self.connection.reload_document(fetched_doc)
        self.assertEqual(u'something else', fetched_doc.field)

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

    @defer.inlineCallbacks
    def testSavingTheDocumentWithConflict(self):
        doc = DummyDocument(field=u"blah blah")
        doc = yield self.connection.save_document(doc)

        second_checkout = yield self.connection.get_document(doc.doc_id)
        second_checkout.field = u"changed field"
        yield self.connection.save_document(second_checkout)

        doc.field = u"this will fail"
        d = self.connection.save_document(doc)
        self.assertFailure(d, ConflictError)
        yield d

    @defer.inlineCallbacks
    def testGettingDocumentUpdatingDeleting(self):
        id = u'test id'
        d = self.connection.get_document(id)
        self.assertFailure(d, NotFoundError)
        yield d

        doc = DummyDocument(doc_id=id, field=u'value')
        yield self.connection.save_document(doc)

        fetched = yield self.connection.get_document(id)
        self.assertEqual(doc.rev, fetched.rev)

        yield self.connection.delete_document(fetched)

        d = self.connection.get_document(id)
        self.assertFailure(d, NotFoundError)
        yield d

    @defer.inlineCallbacks
    def testDeletingAndUpdating(self):
        doc = DummyDocument(field='value')
        yield self.connection.save_document(doc)
        rev = doc.rev

        yield self.connection.delete_document(doc)
        rev2 = doc.rev
        self.assertNotEqual(rev2, rev)

        yield self.connection.save_document(doc)
        rev3 = doc.rev
        self.assertNotEqual(rev3, rev2)

    @defer.inlineCallbacks
    def testOtherSession(self):
        self.changes = list()

        my_doc = DummyDocument(field=u'whatever')
        my_doc = yield self.connection.save_document(my_doc)
        yield self.connection.changes_listener((my_doc.doc_id, ),
                                               self.change_cb)
        my_doc.field = 'sth else'
        yield self.connection.save_document(my_doc)

        yield self.wait_for(self._len_changes(1), 2, freq=0.01)
        doc_id, rev, deleted, own_change = self.changes[0]
        self.assertTrue(own_change)

        other_connection = self.database.get_connection()
        my_doc.field = 'sth different'
        yield other_connection.save_document(my_doc)
        yield self.wait_for(self._len_changes(2), 2, freq=0.01)
        self.assertEqual(my_doc.rev, self.changes[1][1])
        self.assertFalse(self.changes[1][3])

        my_doc.field = 'another'
        yield self.connection.save_document(my_doc)
        yield self.wait_for(self._len_changes(3), 2, freq=0.01)

        my_doc = yield other_connection.delete_document(my_doc)
        yield self.wait_for(self._len_changes(4), 2, freq=0.01)
        doc_id, rev, deleted, own_change = self.changes[3]
        self.assertFalse(own_change)
        self.assertEqual(my_doc.rev, rev)
        self.assertEqual(my_doc.doc_id, doc_id)

        yield self.connection.cancel_listener(my_doc.doc_id)
        yield self.connection.save_document(my_doc)
        # give time to notice the change if the listener is still there
        yield common.delay(None, 0.1)
        self.assertTrue(self._len_changes(4)())

        yield self.connection.disconnect()

    @defer.inlineCallbacks
    def testChangesWithFilterView(self):
        # create design document
        views = (FilteringView, )
        design_doc = view.DesignDocument.generate_from_views(views)
        yield self.connection.save_document(design_doc)

        yield self.connection.changes_listener(FilteringView, self.change_cb,
                                               field='value1')

        self.changes = list()
        my_doc = ViewDocument(field=u'value1')
        my_doc = yield self.connection.save_document(my_doc)
        yield self.wait_for(self._len_changes(1), 2, freq=0.01)
        doc_id, rev, deleted, own_change = self.changes.pop()
        self.assertEqual(doc_id, my_doc.doc_id)
        self.assertEqual(rev, my_doc.rev)
        self.assertTrue(own_change)
        self.assertFalse(deleted)

        other_connection = self.database.get_connection()
        yield other_connection.changes_listener(FilteringView, self.change_cb,
                                               field='value2')
        my_doc2 = ViewDocument(field=u'value2')
        my_doc2 = yield self.connection.save_document(my_doc2)
        yield self.wait_for(self._len_changes(1), 2, freq=0.01)
        doc_id, rev, deleted, own_change = self.changes.pop()

        yield self.connection.disconnect()
        my_doc.value += 1
        my_doc2.value += 1
        yield other_connection.save_document(my_doc)
        yield other_connection.save_document(my_doc2)
        yield self.wait_for(self._len_changes(1), 2, freq=0.01)
        doc_id, rev, deleted, own_change = self.changes.pop()
        self.assertEqual(doc_id, my_doc2.doc_id)

        yield other_connection.disconnect()

    ### methods specific for testing the notification callbacks

    def change_cb(self, doc, rev, deleted, own_change):
        self.changes.append((doc, rev, deleted, own_change))

    def _len_changes(self, expected):

        def check():
            return len(self.changes) == expected

        return check


class CallbacksReceiver(Mock):

    @Mock.stub
    def on_connect(self):
        pass

    @Mock.stub
    def on_disconnect(self):
        pass


class PaisleySpecific(object):

    def setup_receiver(self):
        mock = CallbacksReceiver()
        self.database.add_disconnected_cb(mock.on_disconnect)
        self.database.add_reconnected_cb(mock.on_connect)
        return mock

    @defer.inlineCallbacks
    def testGettingDocsWhileDisconnected(self):
        doc = DummyDocument(field=u'sth')
        doc = yield self.connection.save_document(doc)
        yield self.process.terminate(keep_workdir=True)
        d = self.connection.get_document(doc.doc_id)
        self.assertFailure(d, NotConnectedError)
        yield d
        yield self.process.restart()

    @defer.inlineCallbacks
    @common.attr(timeout=6)
    def testDisconnection(self):
        self.changes = list()
        mock = self.setup_receiver()
        yield self.database.wait_for_state(ConnectionState.connected)

        my_doc = DummyDocument(field=u'whatever', doc_id=u"my_doc")
        my_doc = yield self.connection.save_document(my_doc)
        yield self.connection.changes_listener((my_doc.doc_id, ),
                                               self.change_cb)

        yield self.process.terminate(keep_workdir=True)
        yield self.database.wait_for_state(ConnectionState.disconnected)
        yield common.delay(None, 0.1)
        self.assertCalled(mock, 'on_disconnect', times=1)

        yield self.process.restart()
        yield self.database.wait_for_state(ConnectionState.connected)
        yield common.delay(None, 0.1)
        self.assertCalled(mock, 'on_connect', times=1)

        other_connection = self.database.get_connection()
        my_doc.field = u'sth different'
        yield other_connection.save_document(my_doc)
        yield self.wait_for(self._len_changes(1), 2, freq=0.01)


@common.attr(timescale=0.05)
class EmuDatabaseIntegrationTest(common.IntegrationTest, TestCase):

    def setUp(self):
        common.IntegrationTest.setUp(self)
        self.database = emu_database.Database()
        self.connection = self.database.get_connection()


@attr('slow')
class PaisleyIntegrationTest(common.IntegrationTest, TestCase,
                             PaisleySpecific):

    timeout = 3
    slow = True

    @defer.inlineCallbacks
    def setUp(self):
        yield common.IntegrationTest.setUp(self)
        if database is None:
            raise SkipTest('Skipping the test because of missing '
                           'dependecies: %r' % import_error)

        try:
            self.process = couchdb.Process(self)
        except DependencyError as e:
            raise SkipTest(str(e))

        yield self.process.restart()

        config = self.process.get_config()
        host, port = config['host'], config['port']
        self.database = database.Database(host, port, 'test')
        self.connection = self.database.get_connection()
        yield self.connection.create_database()

    def tearDown(self):
        self.connection.disconnect()
        self.database.disconnect()
        return self.process.terminate()
