# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import json

from zope.interface import implements

from feat.common import log
from feat.agents import document

from feat.agencies.interface import IDatabaseClient


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
