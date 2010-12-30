# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from feat.common import serialization


documents = dict()


def register(klass):
    global documents
    if klass.document_type in documents:
        raise ValueError('document_type %s already registered!' %
                         klass.document_type)
    documents[klass.document_type] = klass
    serialization.register(klass)
    return klass


@serialization.register
class Document(serialization.Serializable):

    def __init__(self, **fields):
        valid_fields = ('doc_id', 'rev', )
        self._set_fields(valid_fields, fields)

    def _set_fields(self, fields, dictionary):
        for field in fields:
            setattr(self, field, dictionary.get(field, None))

    def snapshot(self):
        res = dict()
        if self.doc_id:
            res['_id'] = self.doc_id
        if self.rev:
            res['_rev'] = self.rev
        return res

    def recover(self, snapshot):
        self.doc_id = snapshot.get('_id', None)
        self.rev = snapshot.get('_rev', None)
