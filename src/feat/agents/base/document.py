# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from feat.common import formatable, serialization

documents = dict()


def register(klass):
    global documents
    if klass.document_type in documents:
        raise ValueError('document_type %s already registered!' %
                         klass.document_type)
    documents[klass.document_type] = klass
    serialization.register(klass)
    return klass


field = formatable.field


@serialization.register
class Document(formatable.Formatable):

    field('doc_id', None, '_id')
    field('rev', None, '_rev')
