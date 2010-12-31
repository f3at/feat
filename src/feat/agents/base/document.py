# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import copy

from feat.common import serialization, annotate


documents = dict()


def register(klass):
    global documents
    if klass.document_type in documents:
        raise ValueError('document_type %s already registered!' %
                         klass.document_type)
    documents[klass.document_type] = klass
    serialization.register(klass)
    return klass


class Field(object):

    def __init__(self, name, default, json_name=None):
        self.name = name
        self.default = default
        self.json_name = json_name or name


def field(name, default, json_name=None):
    f = Field(name, default, json_name)
    annotate.injectClassCallback("field", 3, "_register_field", f)


@serialization.register
class Document(serialization.Serializable, annotate.Annotable):

    __metaclass__ = type('MetaDocument', (type(serialization.Serializable),
                                          type(annotate.Annotable), ), {})

    _fields = None
    field('doc_id', None, '_id')
    field('rev', None, '_rev')

    @classmethod
    def _register_field(cls, field):
        if cls._fields is None:
            cls._fields = list()
        cls._fields.append(field)

    def __init__(self, **fields):
        self._set_fields(fields)

    def _set_fields(self, dictionary):
        for field in self._fields:
            # lazy coping of default value, don't touch!
            value = dictionary.get(field.name, None) or\
                    copy.copy(field.default)
            setattr(self, field.name, value)

    # ISerializable

    def snapshot(self):
        res = dict()
        for field in self._fields:
            value = getattr(self, field.name)
            if value is not None:
                res[field.json_name] = value
        return res

    def recover(self, snapshot):
        for field in self._fields:
            # lazy coping of default value, don't touch!
            value = snapshot.get(field.json_name, None) or\
                    copy.copy(field.default)
            setattr(self, field.name, value)
