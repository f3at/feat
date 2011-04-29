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
    klass.type_name = klass.document_type
    serialization.register(klass)
    return klass


def lookup(document_type):
    global documents
    return documents.get(document_type)


field = formatable.field


@serialization.register
class Document(formatable.Formatable):

    field('doc_id', None, '_id', unicode)
    field('rev', None, '_rev', unicode)
