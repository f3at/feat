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
import operator

from twisted.trial.unittest import SkipTest

try:
    from feat.database import driver
except ImportError as e:
    database = None
    import_error = e

from feat.database import emu, view, document, query
from feat.process import couchdb
from feat.process.base import DependencyError
from feat.common import serialization, defer
from feat.agencies.common import ConnectionState

from . import common
from feat.test.common import attr, Mock

from feat.database.interface import ConflictError, NotFoundError
from feat.database.interface import NotConnectedError


@serialization.register
class DummyDocument(document.Document):

    type_name = 'dummy'

    document.field('field', None)
    document.field('value', 0)


@serialization.register
class ViewDocument(document.Document):

    type_name = 'view-dummy'

    document.field('field', None)
    document.field('value', 0)


class FilteringView(view.BaseView):

    name = 'filter_view'

    def filter(doc, request):
        check_request = (not request.get('query') and
                         request['query'].get('field') is not None)
        return (doc.get('.type', None) == 'view-dummy' and
                (not check_request or
                 doc['field'] == request['query']['field']))


VALUE_FIELD = 'value'


class SummingView(view.FormatableView):

    name = 'some_view'
    use_reduce = True

    view.field('value', None)
    view.field('field', None)

    def map(doc):
        if doc['.type'] == 'dummy':
            field = doc.get('field', None)
            yield field, {"value": doc.get(VALUE_FIELD, None),
                          "field": field}

    view.attach_constant(map, 'VALUE_FIELD', VALUE_FIELD)

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
            yield doc.get('field', None), 1

    reduce = "_count"


class GroupCountingView(view.BaseView):

    name = 'group_counting_view'
    use_reduce = True

    def map(doc):
        if doc['.type'] == 'dummy':
            field = doc.get('field', None)
            value = doc.get('value', None)
            key = (field, value)
            yield key, 1

    reduce = "_count"

    @classmethod
    def parse(cls, key, value, reduced):
        if key:
            key = tuple(key)
        return key, value


class TestCase(object):

    @defer.inlineCallbacks
    def testAttachments(self):
        doc = DummyDocument(doc_id=u'some_doc')
        # first just create an attachment
        at = doc.create_attachment('attachment', u'This is attached data',
                                   'text/plain')
        doc = yield self.connection.save_document(doc)

        self.assertEqual(1, len(doc.attachments))
        self.assertIn('attachment', doc.attachments)

        # we do have a data in cache, getting it from there
        body = yield self.connection.get_attachment_body(at)
        self.assertEquals('This is attached data', body)

        # reload the doc and refecth the data
        doc = yield self.connection.reload_document(doc)
        body = yield self.connection.get_attachment_body(at)
        self.assertEquals('This is attached data', body)

        # updating document in a differnt way, check that attachment is still
        # there
        doc.field = 5555555
        doc = yield self.connection.save_document(doc)
        doc = yield self.connection.reload_document(doc)
        self.assertEquals(1, len(doc.attachments))

        # test deleting the uknown attachment
        self.assertRaises(NotFoundError, doc.delete_attachment, 'unknown')
        doc.delete_attachment('attachment')
        doc = yield self.connection.save_document(doc)
        self.assertEquals({}, doc.attachments)

        # getting unknown (already deleted) attachment
        d = self.connection.get_attachment_body(at)
        self.assertFailure(d, NotFoundError)
        yield d

    @defer.inlineCallbacks
    def testQueryingWithRanges(self):
        views = (SummingView, )
        design_doc = view.DesignDocument.generate_from_views(views)[0]
        yield self.connection.save_document(design_doc)

        docs = [
            DummyDocument(field=u'A', value=1),
            DummyDocument(field=u'B', value=1),
            DummyDocument(field=u'C', value=1),
            DummyDocument(field=u'D', value=1)]
        for doc in docs:
            yield self.connection.save_document(doc)

        res = yield self.connection.query_view(SummingView, reduce=False,
                                               startkey='B')
        self.assertEqual(3, len(res))
        res = sorted(res, key=operator.attrgetter('field'))
        self.assertEqual('B', res[0].field)
        self.assertEqual('C', res[1].field)
        self.assertEqual('D', res[2].field)

        res = yield self.connection.query_view(SummingView, reduce=False,
                                               endkey='B')
        self.assertEqual(2, len(res))
        res = sorted(res, key=operator.attrgetter('field'))
        self.assertEqual('A', res[0].field)
        self.assertEqual('B', res[1].field)

        res = yield self.connection.query_view(SummingView, reduce=False,
                                               startkey='B', endkey='C')
        self.assertEqual(2, len(res))
        res = sorted(res, key=operator.attrgetter('field'))
        self.assertEqual('B', res[0].field)
        self.assertEqual('C', res[1].field)

    @defer.inlineCallbacks
    def testCountingWithGroup(self):
        views = (GroupCountingView, )
        design_doc = view.DesignDocument.generate_from_views(views)[0]
        yield self.connection.save_document(design_doc)

        docs = [
            DummyDocument(field=u'key1', value=1),
            DummyDocument(field=u'key2', value=1),
            DummyDocument(field=u'key1', value=2)]
        for doc in docs:
            yield self.connection.save_document(doc)

        res = yield self.connection.query_view(GroupCountingView)
        self.assertEqual([(None, 3)], res)

        res = yield self.connection.query_view(GroupCountingView, group=True)
        dres = dict(res)
        self.assertIn(('key1', 1), dres)
        self.assertIn(('key1', 2), dres)
        self.assertIn(('key2', 1), dres)
        self.assertEqual(dres[('key1', 1)], 1)
        self.assertEqual(dres[('key1', 2)], 1)
        self.assertEqual(dres[('key2', 1)], 1)

        res = yield self.connection.query_view(GroupCountingView,
                                               group_level=1)
        dres = dict(res)
        self.assertIn(('key1', ), dres)
        self.assertIn(('key2', ), dres)
        self.assertEqual(dres[('key1', )], 2)
        self.assertEqual(dres[('key2', )], 1)

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
        design_doc = view.DesignDocument.generate_from_views(views)[0]
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
        yield self.connection.save_document(DummyDocument(value=3))

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
        design_doc = view.DesignDocument.generate_from_views(views)[0]
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

    @defer.inlineCallbacks
    def testGettingChangesAndSequence(self):
        views = (FilteringView, )
        design_doc = view.DesignDocument.generate_from_views(views)[0]
        yield self.connection.save_document(design_doc)

        start_seq = yield self.connection.get_update_seq()
        self.assertIsInstance(start_seq, int)

        doc = yield self.connection.save_document(
            ViewDocument(field=u'value2'))
        seq = yield self.connection.get_update_seq()
        self.assertIsInstance(seq, int)
        self.assertEqual(start_seq + 1, seq)

        # now get the changes
        changes = yield self.connection.get_changes(since=start_seq)
        self.assertIsInstance(changes, dict)
        self.assertIn('results', changes)
        self.assertIn('last_seq', changes)
        self.assertEqual(seq, changes['last_seq'])
        res = changes['results']
        self.assertIsInstance(res, list)
        self.assertEqual(1, len(res))
        self.assertEqual(res[0]['id'], doc.doc_id)
        self.assertEqual(res[0]['changes'][0]['rev'], doc.rev)

        # create doc of different type

        doc2 = yield self.connection.save_document(
            DummyDocument(field=u'value2'))
        changes = yield self.connection.get_changes(since=start_seq)
        self.assertEquals(2, len(changes['results']))

        changes = yield self.connection.get_changes(since=seq)
        self.assertEquals(1, len(changes['results']))
        self.assertEqual(changes['results'][0]['id'], doc2.doc_id)

        changes = yield self.connection.get_changes(FilteringView)
        self.assertEquals(1, len(changes['results']))
        self.assertEqual(changes['results'][0]['id'], doc.doc_id)

    @defer.inlineCallbacks
    def testBulkGet(self):
        docs = []
        for x in range(3):
            doc = yield self.connection.save_document(DummyDocument())
            docs.append(doc)

        # check successful get
        doc_ids = [x.doc_id for x in docs]
        gets = yield self.connection.bulk_get(doc_ids)
        self.assertEqual(docs, gets)

        # prepend nonexisting docs
        gets = yield self.connection.bulk_get(['notexistant'] + doc_ids,
                                              consume_errors=False)
        self.assertEqual(docs, gets[1:])
        self.assertIsInstance(gets[0], NotFoundError)

        # consuming errors is a default
        gets = yield self.connection.bulk_get(['notexistant'] + doc_ids)
        self.assertEqual(docs, gets)

        # now delete one doc, it should work as if it has never been there
        yield self.connection.delete_document(docs[0])

        gets = yield self.connection.bulk_get(doc_ids)
        self.assertEquals(docs[1:], gets)

        gets = yield self.connection.bulk_get(doc_ids, consume_errors=False)
        self.assertEquals(docs[1:], gets[1:])
        self.assertIsInstance(gets[0], NotFoundError)

    @defer.inlineCallbacks
    def testUsingQueryView(self):
        views = (QueryView, )
        design_doc = view.DesignDocument.generate_from_views(views)[0]
        yield self.connection.save_document(design_doc)

        for x in range(20):
            if x % 2 == 0:
                field3 = u"A"
            else:
                field3 = u"B"
            yield self.connection.save_document(
                QueryDoc(field1=x, field2=x % 10, field3=field3))

        C = query.Condition
        E = query.Evaluator
        O = query.Operator
        Q = query.Query
        D = query.Direction

        c1 = C('field1', E.le, 9)
        c2 = C('field2', E.ge, 5)
        c3 = C('field3', E.equals, 'B')
        c4 = C('field1', E.between, (5, 14))

        yield self._query_test([0, 1, 2, 3, 4, 5, 6, 7, 8, 9], c1)
        yield self._query_test([5, 6, 7, 8, 9], c1, O.AND, c2)
        yield self._query_test([0, 1, 2, 3, 4, 5, 6, 7, 8, 9,
                                15, 16, 17, 18, 19], c1, O.OR, c2)
        yield self._query_test([5, 6, 7, 8, 9], c4, O.AND, c2)

        yield self._query_test([1, 3, 5, 7, 9, 11, 13, 15, 17, 19], c3,
                               sorting=[('field1', D.ASC)])
        q = Q(QueryView, c3)
        yield self._query_test([1, 3, 5, 7, 9], q, O.AND, c1,
                               sorting=[('field1', D.ASC)])
        yield self._query_test([13, 11, 9, 7, 5], q, O.AND, c4,
                               sorting=[('field1', D.DESC)])
        yield self._query_test([5, 7, 9], c1, O.AND, c4, O.AND, q)

    @defer.inlineCallbacks
    def _query_test(self, result, *parts, **kwargs):
        q = query.Query(QueryView, *parts, sorting=kwargs.pop('sorting', None))
        res = yield query.select(self.connection, q)
        self.assertEquals(result, [x.field1 for x in res])
        count = yield query.count(self.connection, q)
        self.assertEquals(len(result), count)


    ### methods specific for testing the notification callbacks

    def change_cb(self, doc, rev, deleted, own_change):
        self.changes.append((doc, rev, deleted, own_change))

    def _len_changes(self, expected):

        def check():
            return len(self.changes) == expected

        return check


@serialization.register
class QueryDoc(document.Document):
    type_name = 'query'

    document.field('field1', None)
    document.field('field2', None)
    document.field('field3', None)


class QueryView(query.QueryView):

    name = 'query_view'

    def extract_field1(doc):
        yield doc.get('field1')

    def extract_field2(doc):
        yield doc.get('field2')

    def extract_field3(doc):
        yield doc.get('field3')

    query.field('field1', extract_field1)
    query.field('field2', extract_field2)
    query.field('field3', extract_field3)
    query.document_types(['query'])


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
    skip_coverage = False

    def setUp(self):
        common.IntegrationTest.setUp(self)
        self.database = emu.Database()
        self.connection = self.database.get_connection()


@attr('slow')
class PaisleyIntegrationTest(common.IntegrationTest, TestCase,
                             PaisleySpecific):

    timeout = 4
    slow = True
    skip_coverage = False

    @defer.inlineCallbacks
    def setUp(self):
        yield common.IntegrationTest.setUp(self)
        if driver is None:
            raise SkipTest('Skipping the test because of missing '
                           'dependecies: %r' % import_error)

        try:
            self.process = couchdb.Process(self)
        except DependencyError as e:
            raise SkipTest(str(e))

        yield self.process.restart()

        config = self.process.get_config()
        host, port = config['host'], config['port']
        self.database = driver.Database(host, port, 'test')
        self.connection = self.database.get_connection()
        yield self.connection.create_database()

    def tearDown(self):
        self.connection.disconnect()
        self.database.disconnect()
        return self.process.terminate()
