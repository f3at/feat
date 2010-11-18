# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import uuid
import json

from twisted.internet import defer
from twisted.python import components
from zope.interface import implements

from feat.common import log
from feat.agents import document
from feat.interface.database import IDatabaseClient


class ConflictError(RuntimeError):
    '''
    Raised when we encounter revision mismatch.
    '''


class NotFoundError(RuntimeError):
    '''
    Raised when we request document which is not there
    or has been deleted.
    '''


class Database(log.Logger, log.FluLogKeeper):
    '''
    Imitates the CouchDB server internals.
    The bizare naming used in this class origins from paisley,
    which we want to stay consitent with.
    '''

    log_category = "database"

    def __init__(self):
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)

        # id -> document
        self._documents = {}
        self.connection = Connection(self)

    def saveDoc(self, doc, docId=None):
        '''Imitate sending HTTP request to CouchDB server'''

        self.log("save_document called for doc: %r", doc)

        d = defer.Deferred()

        try:
            if not isinstance(doc, (str, unicode, )):
                raise ValueError('Doc should be either str or unicode')
            doc = json.loads(doc)
            doc = self._set_id_and_revision(doc, docId)

            self._documents[doc['_id']] = doc

            r = Response(ok=True, id=doc['_id'], rev=doc['_rev'])
            d.callback(r)
        except (ConflictError, ValueError, ) as e:
            d.errback(e)

        return d

    def openDoc(self, docId):
        '''Imitated fetching the document from the database.
        Doesnt implement options from paisley to get the old revision or
        get the list of revision.
        '''
        d = defer.Deferred()

        try:
            doc = self._get_doc(docId)
            if doc.get('_deleted', None):
                raise NotFoundError('deleted')
            d.callback(Response(doc))
        except NotFoundError as e:
            d.errback(e)

        return d

    def deleteDoc(self, docId, revision):
        '''Imitates sending DELETE request to CouchDB server'''
        d = defer.Deferred()

        try:
            doc = self._get_doc(docId)
            if doc['_rev'] != revision:
                raise ConflictError("Document update conflict.")
            if doc.get('_deleted', None):
                raise NotFoundError('deleted')
            doc['_rev'] = self._generate_id()
            doc['_deleted'] = True
            self.log('Marking document %r as deleted', docId)
            d.callback(Response(ok=True, id=docId, rev=doc['_rev']))
        except (ConflictError, NotFoundError, ) as e:
            d.errback(e)

        return d

    def _set_id_and_revision(self, doc, doc_id):
        doc_id = doc_id or doc.get('_id', None)
        if doc_id is None:
            doc_id = self._generate_id()
            self.log("Generating new id for the document: %r", doc_id)
        else:
            old_doc = self._documents.get(doc_id, None)
            if old_doc:
                self.log('Checking the old document revision')
                if doc.get('_rev', None) is None or\
                       old_doc['_rev'] != doc['_rev']:
                    raise ConflictError('Document update conflict.')

        doc['_rev'] = self._generate_id()
        doc['_id'] = doc_id

        return doc

    def _get_doc(self, docId):
        doc = self._documents.get(docId, None)
        if not doc:
            raise NotFoundError("missing")
        return doc

    def _generate_id(self):
        return str(uuid.uuid1())


class Connection(log.Logger, log.FluLogKeeper):
    '''API for agency to call against the database.'''

    implements(IDatabaseClient)

    def __init__(self, database):
        self.database = database

    def save_document(self, doc):
        content = doc.get_content()
        content['document_type'] = doc.document_type
        if doc.doc_id:
            content['_id'] = doc.doc_id
        if doc.rev:
            content['_rev'] = doc.rev

        serialized = json.dumps(content)
        d = self.database.saveDoc(serialized, doc.doc_id)
        d.addCallback(doc.update)

        return d

    def get_document(self, id):

        def instantiate(doc):
            doc_type = doc.get('document_type', None)
            if doc_type is None:
                raise RuntimeError("Document fetched from database doesn't "
                                   "have the 'document_type' field")
            factory = document.documents.get(doc_type, None)
            if factory is None:
                raise RuntimeError("Unknown 'document_type' = %s", doc_type)
            return factory(**doc)

        d = self.database.openDoc(id)
        d.addCallback(self._sanitize_unicode_keys)
        d.addCallback(instantiate)

        return d

    def reload_document(self, doc):
        assert isinstance(doc, document.Document)

        def update(resp, doc):
            doc.__class__.__init__(doc, **resp)
            return doc

        d = self.database.openDoc(doc.doc_id)
        d.addCallback(self._sanitize_unicode_keys)
        d.addCallback(update, doc)

        return d

    def delete_document(self, doc):
        assert isinstance(doc, document.Document)

        d = self.database.deleteDoc(doc.doc_id, doc.rev)
        d.addCallback(doc.update)

        return d

    def _sanitize_unicode_keys(self, doc):
        resp = dict()
        for key in doc:
            resp[key.encode('utf-8')] = doc[key]
        return resp

components.registerAdapter(Connection, Database, IDatabaseClient)


class Response(dict):

    pass
