# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

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

import copy
import operator
import os

from twisted.trial.unittest import SkipTest

from feat.database import emu, view, document, query, driver, update, conflicts
from feat.database import links, common as dcommon
from feat.process import couchdb
from feat.process.base import DependencyError
from feat.common import serialization, defer, error, time
from feat.common.text_helper import format_block
from feat.agencies.common import ConnectionState

from . import common
from feat.test.common import attr, Mock

from feat.database.interface import ConflictError, NotFoundError, DatabaseError
from feat.database.interface import NotConnectedError, ResignFromModifying
from feat.database.interface import ConflictResolutionStrategy


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
        check_request = (request.get('query') and
                         request['query'].get('field') is not None)
        return (doc.get('.type', None) == 'view-dummy' and
                (not check_request or
                 doc['field'] == request['query']['field']))


VALUE_FIELD = 'value'


class IncludeDocsView(view.BaseView):

    name = 'include_docs'

    def map(doc):
        if doc.get('.type') == 'dummy':
            yield doc.get('field'), None

    @classmethod
    def parse_view_result(cls, rows, reduced, include_docs):
        if not include_docs:
            # return list of ids
            return [x[2] for x in rows]
        else:
            unserializer = dcommon.CouchdbUnserializer()
            return [unserializer.convert(x[3]) for x in rows]


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


class JSSummingView(view.JavascriptView):

    name = 'some_view'
    use_reduce = True
    design_doc_id = u'featjs'

    map = format_block('''
    function(doc) {
        if (doc[".type"] == "dummy") {
            emit(doc.field, {"value": doc.value, "field": doc.field});
        }
    }''')

    reduce = format_block('''
    function(keys, values) {
        var value = 0;
        for (var i = 0; i < values.length; i += 1) {
            value += values[i].value
        }
        return value;
    }''')


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


### testing query reduce view ###


@serialization.register
class InfoDocument(document.Document):

    type_name = "info-document"

    document.field('field', None)


@serialization.register
class VersionDocument(document.Document):

    type_name = "version-document"

    document.field('version', None)


iter_linked_id = view.iter_linked_id


def version_sorting(value):
    import re
    return tuple(int(x) for x in re.findall(r'[0-9]+', value))


class QueryReduceView(view.BaseView):

    name = 'test_query_view'

    def map(doc):
        if doc.get('.type') == 'info-document':
            yield ('field', doc.get('field')), None
        if doc.get('.type') == 'version-document':
            plain = doc.get('version')
            value = version_sorting(plain)
            for doc_id in iter_linked_id(doc, 'info-document'):
                yield ('version', value), {'_id': doc_id, 'value': plain}

    view.attach_method(map, iter_linked_id)
    view.attach_method(map, version_sorting)


class ReduceQuery(query.Query):

    name = 'test_query_view'

    query.field(query.Field('field', QueryReduceView))
    query.field(query.HighestValueField('version', QueryReduceView,
                                        sorting=version_sorting))

### used to tests update_document() ###


def delete_doc(document):
    return None


def update_dict(document, **keywords):
    changed = False
    for key, value in keywords.items():
        current = getattr(document, key)
        if current != value:
            changed = True
            setattr(document, key, value)

    if changed:
        return document
    else:
        raise ResignFromModifying()

### end ###


class TestCase(object):

    @defer.inlineCallbacks
    def testLinkingDocuments(self):
        views = (links.Join, )
        design_doc = view.DesignDocument.generate_from_views(views)[0]
        yield self.connection.save_document(design_doc)

        docs = []
        for x in [DummyDocument() for x in range(3)]:
            doc = yield self.connection.save_document(x)
            docs.append(doc)

        docs[0].links.create(doc=docs[1])
        docs[0] = yield self.connection.save_document(docs[0])

        # check that it can be fetched from both sides
        fetched1 = yield links.fetch(self.connection, docs[0].doc_id)
        self.assertEqual([docs[1]], fetched1)
        fetched1 = yield links.fetch_one(self.connection, docs[0].doc_id)
        self.assertEqual(docs[1], fetched1)
        fetched2 = yield links.fetch(self.connection, docs[1].doc_id)
        self.assertEqual([docs[0]], fetched2)

        # now use roles
        docs[0].links.create(doc=docs[2], linker_roles=['parent'],
                             linkee_roles=['child'])
        docs[0] = yield self.connection.save_document(docs[0])
        fetched1 = yield links.fetch(self.connection, docs[0].doc_id, 'child')
        self.assertEqual([docs[2]], fetched1)
        fetched2 = yield links.fetch(self.connection, docs[2].doc_id, 'parent')
        self.assertEqual([docs[0]], fetched2)

    @defer.inlineCallbacks
    def testCopyDocument(self):
        doc = DummyDocument(field='first')
        doc = yield self.connection.save_document(doc)

        yield self.connection.copy_document(doc, 'new_id')
        doc2 = yield self.connection.get_document('new_id')
        self.assertIsInstance(doc2, DummyDocument)
        fetched = yield self.connection.get_document('new_id')

        self.assertEqual(doc2, fetched)

        doc = yield self.connection.update_document(doc, update.attributes,
                                                    {'field': 'new value'})
        d = self.connection.copy_document(doc, 'new_id')
        self.assertFailure(d, ConflictError)
        yield d

        yield self.connection.copy_document(doc, 'new_id', fetched.rev)
        doc3 = yield self.connection.get_document('new_id')
        self.assertIsInstance(doc2, DummyDocument)
        self.assertIsInstance(doc3, DummyDocument)
        self.assertEqual('new value', doc3.field)

    @defer.inlineCallbacks
    def testSaveDocumentWithALink(self):
        views = (links.Join, view.DocumentByType)
        for doc in view.DesignDocument.generate_from_views(views):
            yield self.connection.save_document(doc)

        doc = DummyDocument(field='first')
        doc.links.save_and_link(DummyDocument(field='second'),
                                linker_roles=['linkee'])

        yield self.connection.save_document(doc)

        by_type = yield self.connection.query_view(
            view.DocumentByType, reduce=False, include_docs=True,
            **view.DocumentByType.keys(DummyDocument))
        self.assertEqual(2, len(by_type))
        indexed = dict((x.field, x) for x in by_type)
        self.assertEqual(indexed['first'].doc_id,
                         indexed['second'].links.first(DummyDocument))

        fetched = yield links.fetch_one(self.connection,
                                        indexed['first'].doc_id, 'linkee')
        self.assertEqual(indexed['second'], fetched)

    @defer.inlineCallbacks
    def testDeleteDocumentConcurrently(self):
        doc = DummyDocument(field=u'some_doc')
        doc = yield self.connection.save_document(doc)
        saved = copy.deepcopy(doc)
        saved.field = u'other field'
        yield self.connection.save_document(saved)

        result = yield self.connection.update_document(doc, delete_doc)
        self.assertIsInstance(result, DummyDocument)
        d = self.connection.get_document(doc.doc_id)
        self.assertFailure(d, NotFoundError)
        yield d

    @defer.inlineCallbacks
    def testUpdateDocumentConcurrently(self):
        doc = DummyDocument(field=u'some_doc')
        doc = yield self.connection.save_document(doc)
        saved = copy.deepcopy(doc)
        saved.field = u'other field'
        yield self.connection.save_document(saved)

        result = yield self.connection.update_document(doc, update_dict,
                                                       field='new value')
        self.assertIsInstance(result, DummyDocument)
        self.assertEqual('new value', result.field)

        # now check that it doesn't change if it resigns
        result2 = yield self.connection.update_document(saved, update_dict,
                                                       field='new value')
        self.assertIsInstance(result2, DummyDocument)
        self.assertEqual(result2, result)

    @defer.inlineCallbacks
    def testIncludeDocs(self):
        views = (IncludeDocsView, )
        design_doc = view.DesignDocument.generate_from_views(views)[0]
        yield self.connection.save_document(design_doc)

        doc = DummyDocument(field=u'some_doc')
        doc = yield self.connection.save_document(doc)

        res = yield self.connection.query_view(IncludeDocsView)
        self.assertEquals(1, len(res))
        self.assertEquals(doc.doc_id, res[0])

        res = yield self.connection.query_view(IncludeDocsView,
                                               include_docs=True)
        self.assertEquals(1, len(res))
        self.assertEquals(doc, res[0])

    @defer.inlineCallbacks
    def testBinaryAttachments(self):
        gifdata = ("%c" * 35) % (
            0x47, 0x49, 0x46, 0x38, 0x39, 0x61,
            0x01, 0x00, 0x01, 0x00, 0x80, 0xff,
            0x00, 0xff, 0xff, 0xff, 0x00, 0x00,
            0x00, 0x2c, 0x00, 0x00, 0x00, 0x00,
            0x01, 0x00, 0x01, 0x00, 0x00, 0x02,
            0x02, 0x44, 0x01, 0x00, 0x3b)

        doc = DummyDocument(doc_id=u'some_doc')
        # first just create an attachment
        at = doc.create_attachment('attachment', gifdata, 'image/gif')
        doc = yield self.connection.save_document(doc)

        body = yield self.connection.get_attachment_body(at)
        self.assertEquals(gifdata, body)

    @defer.inlineCallbacks
    def testAttachments(self):
        doc = DummyDocument(doc_id=u'some_doc')
        # first just create an attachment
        at = doc.create_attachment('attachment', u'This is attached data',
                                   'text/plain')
        at2 = doc.create_attachment('attachment2',
                                    u'This is other attachments data',
                                    'text/plain')
        at3 = doc.create_attachment('attachment3',
                                    u'This is third data',
                                    'text/plain')
        doc = yield self.connection.save_document(doc)

        self.assertEqual(3, len(doc.attachments))
        self.assertIn('attachment', doc.attachments)
        self.assertIn('attachment2', doc.attachments)
        self.assertIn('attachment3', doc.attachments)

        # we do have a data in cache, getting it from there
        body = yield self.connection.get_attachment_body(at)
        self.assertEquals('This is attached data', body)

        # reload the doc and refecth the data
        doc = yield self.connection.reload_document(doc)
        body = yield self.connection.get_attachment_body(at)
        self.assertEquals('This is attached data', body)
        body = yield self.connection.get_attachment_body(at2)
        self.assertEquals('This is other attachments data', body)
        body = yield self.connection.get_attachment_body(at3)
        self.assertEquals('This is third data', body)

        # updating document in a differnt way, check that attachment is still
        # there
        doc.field = 5555555
        doc = yield self.connection.save_document(doc)
        doc = yield self.connection.reload_document(doc)
        self.assertEquals(3, len(doc.attachments))

        # test deleting the uknown attachment
        self.assertRaises(NotFoundError, doc.delete_attachment, 'unknown')
        doc.delete_attachment('attachment')
        doc = yield self.connection.save_document(doc)

        self.assertEquals(set(['attachment2', 'attachment3']),
                          set(doc.attachments.keys()))

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
        views = (SummingView, CountingView, JSSummingView)
        for design_doc in view.DesignDocument.generate_from_views(views):
            yield self.connection.save_document(design_doc)

        # check formatable view returning empty list
        resp = yield self.connection.query_view(SummingView, reduce=False)
        self.assertIsInstance(resp, list)
        self.assertFalse(resp)

        # check js view returning empty list
        resp = yield self.connection.query_view(JSSummingView, reduce=False)
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

        resp = yield self.connection.query_view(JSSummingView, reduce=False)
        self.assertIsInstance(resp, list)
        self.assertEqual(1, len(resp))
        self.assertIsInstance(resp[0], tuple)
        self.assertIsInstance(resp[0][1], dict)
        self.assertEqual(2, resp[0][1]['value'])

        # now check counting view
        resp = yield self.connection.query_view(CountingView)
        self.assertEqual(1, resp[0])

        # use summing view with reduce
        resp = yield self.connection.query_view(SummingView)
        self.assertEqual([2], resp)

        resp = yield self.connection.query_view(JSSummingView)
        self.assertEqual([(None, 2)], resp)

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

        resp = yield self.connection.query_view(JSSummingView, reduce=False)
        self.assertIsInstance(resp, list)
        self.assertEqual(2, len(resp))
        self.assertIsInstance(resp[0], tuple)
        self.assertIsInstance(resp[0][1], dict)
        self.assertIn(resp[0][1]['value'], (2, 3, ))
        self.assertIsInstance(resp[1][1], dict)
        self.assertIn(resp[1][1]['value'], (2, 3, ))

        # check that reduce works as well
        resp = yield self.connection.query_view(SummingView)
        self.assertEqual([5], resp)

        resp = yield self.connection.query_view(JSSummingView)
        self.assertEqual([(None, 5)], resp)

        # finnally check the counting view works as expected
        resp = yield self.connection.query_view(CountingView)
        self.assertEqual(2, resp[0])

        # change value of first doc and check that sum changed
        doc1.value = 10
        doc1 = yield self.connection.save_document(doc1)
        resp = yield self.connection.query_view(SummingView)
        self.assertEqual([13], resp)

        resp = yield self.connection.query_view(JSSummingView)
        self.assertEqual([(None, 13)], resp)

        # now delete it
        yield self.connection.delete_document(doc1)
        resp = yield self.connection.query_view(SummingView)
        self.assertEqual([3], resp)

        resp = yield self.connection.query_view(JSSummingView)
        self.assertEqual([(None, 3)], resp)

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
    def testReduceFieldInQueryView(self):
        '''
        In this testcase the query view index is created from 2 types of
        documents. The version field as a highest value out of the set of
        linked documents.
        '''
        views = (QueryReduceView, )
        for design_doc in view.DesignDocument.generate_from_views(views):
            yield self.connection.save_document(design_doc)

        # field -> versions to create
        mapping = [
            ('A', ['1.2.3', '11.2.3', '2.1,4']),
            ('B', ['1.2.4', '5.3.1']),
            ('C', ['5.6.7']),
            ('D', [])]

        saved = list()

        for field, versions in mapping:
            d = yield self.connection.save_document(InfoDocument(field=field))
            saved.append(d)
            for version in versions:
                v = VersionDocument(version=version)
                v.links.create(doc=d)
                yield self.connection.save_document(v)

        C = query.Condition
        E = query.Evaluator
        Q = ReduceQuery
        D = query.Direction

        q = Q(include_value=["version"])
        res = yield query.select(self.connection, q)
        self.assertEqual(saved, res) # its sorted by first field
        # the version fields are set correctly
        self.assertEqual('11.2.3', res[0].version)
        self.assertEqual('5.3.1', res[1].version)
        self.assertEqual('5.6.7', res[2].version)
        self.assertEqual(None, res[3].version)

        q = Q(sorting=('version', D.ASC))
        res = yield query.select(self.connection, q)
        self.assertEqual([saved[0], saved[2], saved[1], saved[3]], res)

        q = Q(C('version', E.equals, '11.2.3'))
        res = yield query.select(self.connection, q)
        self.assertEqual([saved[0]], res)

    @defer.inlineCallbacks
    def testUsingQueryView(self):
        views = (QueryView, )
        for design_doc in view.DesignDocument.generate_from_views(views):
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
        Q = DummyQuery
        D = query.Direction

        c1 = C('field1', E.le, 9)
        c2 = C('field2', E.ge, 5)
        c3 = C('field3', E.equals, 'B')
        c4 = C('field1', E.between, (5, 14))

        yield self._query_test([0, 1, 2, 3, 4, 5, 6, 7, 8, 9], c1)
        yield self._query_test([9, 8, 7, 6, 5, 4, 3, 2, 1, 0], c1,
                               sorting=('field1_resorted', D.ASC))
        yield self._query_test([5, 6, 7, 8, 9], c1, O.AND, c2)
        yield self._query_test([0, 1, 2, 3, 4, 5, 6, 7, 8, 9,
                                15, 16, 17, 18, 19], c1, O.OR, c2,
                               order_kept=10)
        yield self._query_test([5, 6, 7, 8, 9], c4, O.AND, c2)

        yield self._query_test([1, 3, 5, 7, 9, 11, 13, 15, 17, 19], c3,
                               sorting=('field1', D.ASC))
        yield self._query_test([19, 17, 15, 13, 11, 9, 7, 5, 3, 1],
                               c3, sorting=('field1_resorted', D.ASC))
        q = Q(c3)
        yield self._query_test([1, 3, 5, 7, 9], q, O.AND, c1,
                               sorting=('field1', D.ASC))
        yield self._query_test([13, 11, 9, 7, 5], q, O.AND, c4,
                               sorting=('field1', D.DESC))
        yield self._query_test([5, 7, 9], c1, O.AND, c4, O.AND, q)

        yield self._query_values('field1', set(range(20)))
        yield self._query_values('field2', set(range(10)))
        yield self._query_values('field3', set(['A', 'B']))
        d = self._query_values('unknown', set(['A', 'B']))
        self.assertFailure(d, ValueError)
        yield d

        # now check reductions with sum
        q = Q(c1, aggregate=[['sum', 'field1']])
        res = yield query.select_ids(self.connection, q)
        self.assertEqual([sum(range(10))], res.aggregations)

    @defer.inlineCallbacks
    def testQueryViewDeletedDocs(self):
        views = (QueryView, )
        for design_doc in view.DesignDocument.generate_from_views(views):
            yield self.connection.save_document(design_doc)
        doc = yield self.connection.save_document(
            QueryDoc(field1=1, field2=1, field3=u"A"))
        yield self._query_test([1], query.Condition(
            'field1', query.Evaluator.equals, 1))
        yield self.connection.delete_document(doc)
        yield common.delay(None, 0.1)
        yield self._query_test([], query.Condition(
            'field1', query.Evaluator.equals, 1))

    @defer.inlineCallbacks
    def _query_values(self, field, expected):
        values = yield query.values(self.connection,
                                    DummyQuery(), field)
        self.assertEqual(expected, set(values))

    @defer.inlineCallbacks
    def _query_test(self, expected, *parts, **kwargs):
        q = DummyQuery(*parts, sorting=kwargs.pop('sorting', None))
        order_kept = kwargs.pop('order_kept', None)
        res = yield query.select(self.connection, q)
        result = [x.field1 for x in res]
        if order_kept:
            # sometimes fields are expected to come in random order
            self.assertEquals(expected[:order_kept], result[:order_kept])
            self.assertEquals(set(expected), set(result))
        else:
            self.assertEquals(expected, result)

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


class QueryView(view.BaseView):

    name = 'query_view'

    def map(doc):
        if doc.get('.type') != 'query':
            return
        for field in ('field1', 'field2', 'field3'):
            yield (field, doc.get(field)), None
        yield ('field1_resorted', 100 - doc.get('field1')), None


class DummyQuery(query.Query):

    query.field(query.Field('field1', QueryView, keeps_value=True))
    query.field(query.Field('field2', QueryView, keeps_value=True))
    query.field(query.Field('field3', QueryView, keeps_value=True))

    def resort(value):
        return 100 - value

    query.field(query.Field('field1_resorted', QueryView, sorting=resort))


class CallbacksReceiver(Mock):

    @Mock.stub
    def on_connect(self):
        pass

    @Mock.stub
    def on_disconnect(self):
        pass


class CouchdbSpecific(object):

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
class EmuDatabaseTest(common.IntegrationTest, TestCase):
    skip_coverage = False

    def setUp(self):
        common.IntegrationTest.setUp(self)
        self.database = emu.Database()
        self.connection = self.database.get_connection()


class NonEmuTests(object):

    def testFilteredChanges404(self):

        def listener(doc_id, rev, deleted, own_change):
            pass

        d = self.connection.changes_listener(view.DocumentByType, listener)
        self.assertFailure(d, NotFoundError)
        return d

    @defer.inlineCallbacks
    def replication_test_setup(self):
        host, port = self.database.host, self.database.port
        dbname = self.database.db_name
        try:
            rconnection = yield conflicts.configure_replicator_database(
                host, port)
        except ValueError as e:
            self.database.disconnect()
            raise SkipTest(str(e))

        @defer.inlineCallbacks
        def cleanup_replications():
            to_delete = yield rconnection.query_view(conflicts.Replications,
                                                     keys=[("source", 'temp'),
                                                           ("source", dbname),
                                                           ("target", 'temp'),
                                                           ("target", dbname)])
            to_delete = set(x[2] for x in to_delete)
            for row in to_delete:
                yield rconnection.update_document(row, update.delete)
        yield cleanup_replications()

        db2 = driver.Database(host, port, 'temp')
        version = yield db2.get_version()
        if version < (1, 2, 0):
            raise SkipTest('This testcase requires at least couchdb 1.2.0')
        try:
            yield db2.create_db()
        except DatabaseError:
            yield db2.delete_db()
            yield db2.create_db()
        connection2 = db2.get_connection()
        for connection in (self.connection, connection2):
            for doc in view.DesignDocument.generate_from_views([
                conflicts.Conflicts, conflicts.UpdateLogs,
                conflicts.Replication]):
                yield connection.save_document(doc)

        @defer.inlineCallbacks
        def cleanup():
            yield cleanup_replications()

            yield rconnection.disconnect()
            yield rconnection.database.disconnect()
            if 'KEEP_TEST_COUCHDB' not in os.environ:
                yield db2.delete_db()
            yield connection2.disconnect()
            yield db2.disconnect()

        self.addCleanup(cleanup)

        defer.returnValue((rconnection, connection2, dbname))

    @defer.inlineCallbacks
    def testResolvingFakeMergeConflict(self):
        '''
        This testcase checks the situation when the partitions have ad-hoc
        created instance of the documents with merge strategy. The update
        logs are missing, although they are not needed because the boyd of
        the documents is the same (only the revision is different).
        '''
        rconnection, connection2, dbname = yield self.replication_test_setup()
        doc_id = "test_doc"

        doc1 = ConcurrentDoc(doc_id=doc_id, field1=1, field2=[1, 2, 3])
        doc1 = yield self.connection.save_document(doc1)

        doc2 = ConcurrentDoc(doc_id=doc_id, field1=5, field2=[1, 2, 3])
        doc2 = yield connection2.save_document(doc2)
        doc2.field1 = 1
        doc2 = yield connection2.save_document(doc2)

        yield replicate(rconnection, dbname, 'temp')
        yield replicate(rconnection, 'temp', dbname)
        yield self.assert_conflicts(connection2, doc1)
        yield self.assert_conflicts(self.connection, doc2)

        yield conflicts.solve(connection2, doc_id)
        yield conflicts.solve(self.connection, doc_id)

        # conflicts are solved
        yield self.assert_conflicts(connection2)
        yield self.assert_conflicts(self.connection)

    @defer.inlineCallbacks
    def testResolvingConflicts(self):
        rconnection, connection2, dbname = yield self.replication_test_setup()

        # create a replication document in each database so that
        # the logic in cleanup_logs() know that the docs are there
        yield replicate(rconnection, dbname, 'temp')
        yield replicate(rconnection, 'temp', dbname)

        doc = ConcurrentDoc(field1=1, field2=[1, 2, 3])
        doc = yield self.connection.save_document(doc)

        # # make sure this is commited
        yield self.connection.database.couchdb_call(
            self.connection.database.couchdb.post,
            '/%s/_ensure_full_commit' % (dbname, ))

        yield replicate(rconnection, dbname, 'temp')

        # check that it reached the target
        doc2 = yield connection2.get_document(doc.doc_id)
        self.assertEqual(doc, doc2)

        # doing the cleaunp on each partition should not delete anything,
        # as there are no updates yet
        yield self.assert_cleanup(0, self.connection, rconnection)
        yield self.assert_cleanup(0, connection2, rconnection)

        # do some concurrent updates
        doc = yield self.connection.update_document(
            doc, update.attributes, {'field1': 5})
        rev1 = doc.rev
        doc = yield self.connection.update_document(
            doc, update.append_to_list, 'field2', 'A')
        rev2 = doc.rev
        self.assertEqual([1, 2, 3, 'A'], doc.field2)
        doc2 = yield connection2.update_document(
            doc2, update.append_to_list, 'field2', 'B')
        self.assertEqual([1, 2, 3, 'B'], doc2.field2)
        rev1b = doc2.rev
        doc2 = yield connection2.update_document(
            doc2, update.append_to_list, 'field2', 'C')
        self.assertEqual([1, 2, 3, 'B', 'C'], doc2.field2)

        # assert update logs where created
        logs1 = yield self.assert_logs(2, self.connection)
        self.assertEqual(rev1, logs1[0].rev_to)
        part = logs1[0].partition_tag
        self.assertIsNot(None, part)
        self.assertEqual(update.attributes, logs1[0].handler)
        self.assertEqual(rev1, logs1[1].rev_from)
        self.assertEqual(rev2, logs1[1].rev_to)
        self.assertEqual(part, logs1[1].partition_tag)
        self.assertEqual(update.append_to_list, logs1[1].handler)

        logs2 = yield self.assert_logs(2, connection2)
        self.assertEqual(2, len(logs2))
        self.assertEqual(rev1b, logs2[0].rev_to)
        part2 = logs2[0].partition_tag
        self.assertNotEqual(part2, part)

        # doing the cleaunp now should not delete anything, because neither
        # of partitions replicated their changes
        yield self.assert_cleanup(0, self.connection, rconnection)
        yield self.assert_cleanup(0, connection2, rconnection)

        # replicate the changes
        yield replicate(rconnection, dbname, 'temp')

        yield self.assert_logs(4, connection2)
        yield self.assert_conflicts(connection2, doc)
        # the other partition does not notive the conflict
        yield self.assert_conflicts(self.connection)

        # doing the cleaunp now should not delete the logs, because
        # they are done for the document which is currently in conflict state
        yield self.assert_cleanup(0, connection2, rconnection)
        # This database is not in conflict state because the changes on the
        # other partion were not propagated here. It sent its logs to the
        # other partion, so its free to delete its logs.
        yield self.assert_cleanup(2, self.connection, rconnection)

        # solve the conflict of the partition which
        yield conflicts.solve(connection2, doc.doc_id)
        merged = yield connection2.reload_document(doc)
        self.assertEqual([1, 2, 3, 'A', 'B', 'C'], merged.field2)
        self.assertEqual(5, merged.field1)

        yield self.assert_conflicts(connection2)

        # the other partition does not need a conflict resolution
        # this does nothing..
        yield conflicts.solve(self.connection, doc.doc_id)

        # The cleanup on the partition with the conflict solved
        # can get rid of the logs coming from the other partion.
        # The other partition has nothing to cleanup anymore
        yield self.assert_cleanup(0, self.connection, rconnection)
        yield self.assert_cleanup(2, connection2, rconnection)

        # Before the solution is replicated back, we make another change on
        # the document.
        doc = yield self.connection.update_document(
            doc, update.append_to_list, 'field2', 'D')
        self.assertEqual([1, 2, 3, 'A', 'D'], doc.field2)

        # replicate the solution back, replication is done with the filter
        # so the update logs are not deleted on the target
        yield replicate(rconnection, 'temp', dbname,
                        filter=u'featjs/replication')
        # The partition solving the first conflict is finally
        # ready to get rid of its logs.
        yield self.assert_cleanup(3, connection2, rconnection)

        # we are in conflict state, because of the change adding 'D'
        yield self.assert_conflicts(self.connection, doc)
        # but we can solve it
        yield conflicts.solve(self.connection, doc.doc_id)
        yield self.assert_conflicts(self.connection)
        doc = yield self.connection.reload_document(doc)
        self.assertEqual([1, 2, 3, 'A', 'B', 'C', 'D'], doc.field2)

        # there is 5 of them now in the target, the third one comes from
        # solving the conflict, 4th from update adding 'D', 5th from
        # solving second conflict
        yield self.assert_logs(5, self.connection)
        # 3 of them can be cleaned up, because they are already included in
        # the revision we have
        yield self.assert_cleanup(3, self.connection, rconnection)

        # after solving the second conflict replicate the solution
        # to temp database
        yield replicate(rconnection, dbname, 'temp',
                        filter=u'featjs/replication')
        # there should be no conflict
        yield self.assert_conflicts(connection2)

        # we can remove the remaining logs
        yield self.assert_cleanup(2, self.connection, rconnection)
        yield self.assert_cleanup(2, connection2, rconnection)

        # assert that there are no logs left
        for connection in (self.connection, connection2):
            yield self.assert_logs(0, connection)

    def assert_logs(self, expected, connection):
        keys = conflicts.UpdateLogs.all()
        keys['include_docs'] = True
        d = connection.query_view(conflicts.UpdateLogs, **keys)
        d.addCallback(defer.keep_param,
                      lambda logs: self.assertEqual(expected, len(logs)))
        return d

    def assert_cleanup(self, expected, connection, rconnection):
        d = conflicts.cleanup_logs(connection, rconnection)
        d.addCallback(self.assertEqual, expected)
        return d

    @defer.inlineCallbacks
    def assert_conflicts(self, connection, *docs):
        expected = [(doc.doc_id, None, doc.doc_id) for doc in docs]
        conf = yield connection.query_view(conflicts.Conflicts)
        self.assertEqual(expected, conf)


@defer.inlineCallbacks
def replicate(connection, source, target, **options):
    r = replication_doc(source, target, **options)
    r = yield connection.save_document(r)
    yield time.wait_for(replication_completed, 5, connection, r['_id'])


@defer.inlineCallbacks
def replication_completed(connection, doc_id):
    doc = yield connection.get_document(doc_id)
    state = doc.get('_replication_state')
    defer.returnValue(state == 'completed')


@serialization.register
class ConcurrentDoc(document.Document):

    conflict_resolution_strategy = ConflictResolutionStrategy.merge

    document.field('field1', None)
    document.field('field2', None)


def replication_doc(source, target, **options):
    doc = dict(options)
    doc.update({'source': unicode(source), 'target': unicode(target)})
    return doc


@attr('slow')
class RemoteDatabaseTest(common.IntegrationTest, TestCase, NonEmuTests):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.IntegrationTest.setUp(self)
        if 'TEST_COUCHDB' not in os.environ:
            raise SkipTest("This test case can be used to test the driver \n"
                           "against the couchdb/bigcouch instance which is \n"
                           "not started/stopped by the test case. \n"
                           "To use it you need to set the TEST_COUCHDB \n"
                           "environment variable to host:port, for example: \n"
                           "export TEST_COUCHDB=localhost:15984")
        try:
            host, port = os.environ['TEST_COUCHDB'].split(":")
            port = int(port)
        except:
            raise SkipTest("Invalid value for TEST_COUCHDB environment\n"
                           "variable: %r. Valid setting would be: \n"
                           "export TEST_COUCHDB=localhost:15984" %
                           (os.environ['TEST_COUCHDB'], ))
        try:
            username, password = os.environ['TEST_COUCHDB_AUTH'].split(':')
        except:
            username = password = None

        db_name = self._testMethodName.lower()
        self.database = driver.Database(host, port, db_name,
                                        username, password)

        try:
            yield self.database.create_db()
        except DatabaseError:
            yield self.database.delete_db()
            yield self.database.create_db()
        self.connection = self.database.get_connection()

    @defer.inlineCallbacks
    def tearDown(self):
        if 'KEEP_TEST_COUCHDB' not in os.environ:
            try:
                yield self.database.delete_db()
            except Exception as e:
                error.handle_exception(self, e,
                                       "Failed to delete the test database")
        self.connection.disconnect()
        self.database.disconnect()
        yield common.IntegrationTest.tearDown(self)


@attr('slow')
class CouchdbIntegrationTest(common.IntegrationTest, TestCase,
                             CouchdbSpecific, NonEmuTests):

    timeout = 4
    slow = True
    skip_coverage = False

    @defer.inlineCallbacks
    def setUp(self):
        yield common.IntegrationTest.setUp(self)
        if 'COUCHDB_DUMP' in os.environ:
            driver.CouchDB.dump = open(self._testMethodName.lower() + ".dump",
                                       'w')
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
