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
from feat.agents import document
from feat.agencies.interface import ConflictError, NotFoundError
from feat.process import couchdb
from feat.process.base import DependencyError

from . import common
from feat.test.common import attr


@document.register
class DummyDocument(document.Document):

    document_type = "dummy"

    def __init__(self, field=None, **kwargs):
        document.Document.__init__(self, **kwargs)
        self.field = field

    def get_content(self):
        return dict(field=self.field)


class TestCase(object):

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

    @defer.inlineCallbacks
    def testSavingTheDocumentWithConflict(self):
        doc = DummyDocument(field="blah blah")
        doc = yield self.connection.save_document(doc)

        second_checkout = yield self.connection.get_document(doc.doc_id)
        second_checkout.field = "changed field"
        yield self.connection.save_document(second_checkout)

        doc.field = "this will fail"
        d = self.connection.save_document(doc)
        self.assertFailure(d, ConflictError)
        yield d

    @defer.inlineCallbacks
    def testGettingDocumentUpdatingDeleting(self):
        id = 'test id'
        d = self.connection.get_document(id)
        self.assertFailure(d, NotFoundError)
        yield d

        doc = DummyDocument(_id=id, field='value')
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


class EmuDatabaseIntegrationTest(common.IntegrationTest, TestCase):

    def setUp(self):
        self.database = emu_database.Database()
        self.connection = self.database.get_connection(None)


@attr('slow')
class PaisleyIntegrationTest(common.IntegrationTest, TestCase):

    timeout = 3
    slow = True

    @defer.inlineCallbacks
    def setUp(self):
        if database is None:
            raise SkipTest('Skipping the test because of missing '
                           'dependecies: %r' % import_error)

        try:
            self.process = couchdb.Process()
        except DependencyError as e:
            raise SkipTest(str(e))

        yield self.process.restart()

        host, port = self.process.config['host'], self.process.config['port']
        self.database = database.Database(host, port, 'test')
        yield self.database.createDB()
        self.connection = self.database.get_connection(None)

    def tearDown(self):
        return self.process.terminate()
