# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from zope.interface import implements

from feat.common import log
from feat.common.serialization import json
from feat.agents.base import document

from feat.agencies.interface import IDatabaseClient


class Connection(log.Logger, log.FluLogKeeper):
    '''API for agency to call against the database.'''

    implements(IDatabaseClient)

    def __init__(self, database):
        self.database = database
        self.serializer = json.Serializer()
        self.unserializer = json.PaisleyUnserializer()

    def save_document(self, doc):
        serialized = self.serializer.convert(doc)
        d = self.database.saveDoc(serialized, doc.doc_id)
        d.addCallback(self.update_id_and_rev, doc)
        return d

    def get_document(self, id):
        d = self.database.openDoc(id)
        d.addCallback(self.unserializer.convert)
        return d

    def reload_document(self, doc):
        assert isinstance(doc, document.Document)
        return self.get_document(doc.doc_id)

    def delete_document(self, doc):
        assert isinstance(doc, document.Document)
        d = self.database.deleteDoc(doc.doc_id, doc.rev)
        d.addCallback(self.update_id_and_rev, doc)
        return d

    def update_id_and_rev(self, resp, doc):
        doc.doc_id = unicode(resp.get('id', None))
        doc.rev = unicode(resp.get('rev', None))
        return doc
