# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import copy

from feat.common import serialization, annotate


class Field(object):

    def __init__(self, name, default, serialize_as=None):
        self.name = name
        self.default = default
        self.serialize_as = serialize_as or name

    def __repr__(self):
        return "%r default %r" % (self.name, self.default, )


def field(name, default, serialize_as=None):
    f = Field(name, default, serialize_as)
    annotate.injectClassCallback("field", 3, "_register_field", f)


class Formatable(serialization.Serializable, annotate.Annotable):

    __metaclass__ = type('MetaFormatable', (type(serialization.Serializable),
                                            type(annotate.Annotable), ), {})

    _fields = list()

    @classmethod
    def __class__init__(cls, name, bases, dct):
        find = [x for x in bases if getattr(cls, '_fields', False)]

        if len(find) == 1:
            cls._fields = copy.deepcopy(bases[0]._fields)

    @classmethod
    def _register_field(cls, field):
        # remove field with this name if already present (overriding defaults)
        [cls._fields.remove(x) for x in cls._fields if x.name == field.name]
        cls._fields.append(field)

    def __init__(self, **fields):
        self._set_fields(fields)

    def __repr__(self):
        return "<%s %r>" % (type(self).__name__, self.snapshot(), )

    def _set_fields(self, dictionary):
        for key in dictionary:
            find = [x for x in self._fields if x.name == key]
            if len(find) != 1:
                raise AttributeError(
                    "Class %r doesn't have the %r attribute." %\
                    (type(self), key, ))

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
                res[field.serialize_as] = value
        return res

    def recover(self, snapshot):
        for field in self._fields:
            # lazy coping of default value, don't touch!
            value = snapshot.get(field.serialize_as, None) or\
                    copy.copy(field.default)
            setattr(self, field.name, value)
