# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import copy
import uuid
import json

from twisted.internet import defer, reactor
from zope.interface import implements

from feat.common import log

from feat.agencies.interface import (IDbConnectionFactory,
                                     IDatabaseDriver,
                                     ConflictError,
                                     NotFoundError)
from feat.agencies.database import Connection, ChangeListenerMixin


class Database(log.Logger, log.FluLogKeeper, ChangeListenerMixin):

    implements(IDbConnectionFactory, IDatabaseDriver)

    '''
    Imitates the CouchDB server internals.
    '''

    log_category = "database"

    def __init__(self):
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)
        ChangeListenerMixin.__init__(self)

        # id -> document
        self._documents = {}

    ### IDbConnectionFactory

    def get_connection(self):
        return Connection(self)

    ### IDatabaseDriver

    def save_doc(self, doc, doc_id=None):
        '''Imitate sending HTTP request to CouchDB server'''

        self.log("save_document called for doc: %r", doc)

        d = defer.Deferred()

        try:
            if not isinstance(doc, (str, unicode, )):
                raise ValueError('Doc should be either str or unicode')
            doc = json.loads(doc)
            doc = self._set_id_and_revision(doc, doc_id)

            self._documents[doc['_id']] = doc

            r = Response(ok=True, id=doc['_id'], rev=doc['_rev'])
            self._trigger_change(doc['_id'], doc['_rev'])
            d.callback(r)
        except (ConflictError, ValueError, ) as e:
            d.errback(e)

        return d

    def open_doc(self, doc_id):
        '''Imitated fetching the document from the database.
        Doesnt implement options from paisley to get the old revision or
        get the list of revision.
        '''
        d = defer.Deferred()

        try:
            doc = self._get_doc(doc_id)
            doc = copy.deepcopy(doc)
            if doc.get('_deleted', None):
                raise NotFoundError('deleted')
            d.callback(Response(doc))
        except NotFoundError as e:
            d.errback(e)

        return d

    def delete_doc(self, doc_id, revision):
        '''Imitates sending DELETE request to CouchDB server'''
        d = defer.Deferred()

        try:
            doc = self._get_doc(doc_id)
            if doc['_rev'] != revision:
                raise ConflictError("Document update conflict.")
            if doc.get('_deleted', None):
                raise NotFoundError('deleted')
            doc['_rev'] = self._generate_id()
            doc['_deleted'] = True
            self.log('Marking document %r as deleted', doc_id)
            self._trigger_change(doc['_id'], doc['_rev'])
            d.callback(Response(ok=True, id=doc_id, rev=doc['_rev']))
        except (ConflictError, NotFoundError, ) as e:
            d.errback(e)

        return d

    ### private

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
        return unicode(uuid.uuid1())


class Response(dict):

    pass
