from feat.common import reflect

from feat.common.serialization import base

UNICODE_ATOM = "unicode"
UNICODE_FORMAT_ATOM = "UTF-8"

BOOL_ATOM = "boolean"
BOOL_TRUE_ATOM = "true"
BOOL_FALSE_ATOM = "false"
NONE_ATOM = "None"

TUPLE_ATOM = "tuple"
LIST_ATOM = "list"
SET_ATOM = "set"
DICT_ATOM = "dictionary"

CLASS_ATOM = "class"
ENUM_ATOM = "enum"
EXTERNAL_ATOM = "external"

REFERENCE_ATOM = "reference"
DEREFERENCE_ATOM = "dereference"


class Serializer(base.Serializer):
    '''Serialize any python structure into s-expression compatible
    with twisted.spread.jelly.'''

    def __init__(self, post_converter=None, externalizer=None):
        base.Serializer.__init__(self, post_converter=post_converter,
                                 externalizer=externalizer)

    def pack_unicode(self, value):
        return [UNICODE_ATOM, value.encode(UNICODE_FORMAT_ATOM)]

    def pack_bool(self, value):
        return [BOOL_ATOM, BOOL_TRUE_ATOM if value else BOOL_FALSE_ATOM]

    def pack_none(self, value):
        return [NONE_ATOM]

    def pack_enum(self, value):
        return [ENUM_ATOM, reflect.canonical_name(value), int(value)]

    def pack_tuple(self, values):
        return [TUPLE_ATOM] + values

    def pack_list(self, values):
        return [LIST_ATOM] + values

    def pack_dict(self, items):
        return [DICT_ATOM] + items

    def pack_set(self, values):
        return [SET_ATOM] + values

    def pack_reference(self, value):
        return [REFERENCE_ATOM] + value

    def pack_dereference(self, value):
        return [DEREFERENCE_ATOM, value]

    def pack_type(self, value):
        return [CLASS_ATOM, reflect.canonical_name(value)]

    def pack_external(self, value):
        return [EXTERNAL_ATOM] + value

    def pack_frozen_instance(self, value):
        content, = value
        return content

    def pack_frozen_function(self, value):
        return reflect.canonical_name(value)

    def pack_frozen_method(self, value):
        return reflect.canonical_name(value)


class Unserializer(base.Unserializer):
    '''Unserialize a structure serialized with L{sexp.Serializer}.'''

    pass_through_types = set([str, int, long, float])

    def __init__(self, pre_converter=None, registry=None, externalizer=None):
        base.Unserializer.__init__(self, pre_converter=pre_converter,
                                   registry=registry,
                                   externalizer=externalizer)

    ### Overridden Methods ###

    def analyse_data(self, data):
        vtype = type(data)

        if vtype is not list:
            return None

        type_name = data[0]

        # We assume that if it's nothing we know about, it's an instance
        default = (None, Unserializer.unpack_instance)
        return self._unpackers.get(type_name, default)

    ### Private Methods ###

    def unpack_unicode(self, data):
        _, value = data
        if not isinstance(value, str):
            raise TypeError("Invalid %s value type: %r"
                            % (UNICODE_ATOM, value))
        return value.decode(UNICODE_FORMAT_ATOM)

    def unpack_bool(self, data):
        _, value = data
        if value == BOOL_TRUE_ATOM:
            return True
        if value == BOOL_FALSE_ATOM:
            return False
        raise ValueError("Invalid %s value: %r" % (BOOL_ATOM, value))

    def unpack_none(self, data):
        _, = data
        return None

    def unpack_enum(self, data):
        _, enum_name, enum_value = data
        enum_class = self.restore_type(enum_name)
        return enum_class.get(enum_value)

    def unpack_external(self, data):
        _, ext_id = data
        return self.restore_external(ext_id)

    def unpack_type(self, data):
        _, type_name, = data
        return self.restore_type(type_name)

    def unpack_instance(self, data):
        type_name, value = data
        return self.restore_instance(type_name, value)

    def unpack_reference(self, data):
        _, refid, value = data
        return self.restore_reference(refid, value)

    def unpack_dereference(self, data):
        _, refid = data
        return self.restore_dereference(refid)

    def unpack_tuple(self, data):
        return tuple([self.unpack_data(d) for d in data[1:]])

    def unpack_list(self, container, data):
        container.extend([self.unpack_data(d) for d in data[1:]])

    def unpack_set(self, container, data):
        container.update([self.unpack_data(d) for d in data[1:]])

    def unpack_dict(self, container, data):
        container.update([(self.unpack_data(k), self.unpack_data(v))
                          for k, v in data[1:]])

    _unpackers = {UNICODE_ATOM: (None, unpack_unicode),
                  BOOL_ATOM: (None, unpack_bool),
                  NONE_ATOM: (None, unpack_none),
                  TUPLE_ATOM: (None, unpack_tuple),
                  CLASS_ATOM: (None, unpack_type),
                  ENUM_ATOM: (None, unpack_enum),
                  EXTERNAL_ATOM: (None, unpack_external),
                  REFERENCE_ATOM: (None, unpack_reference),
                  DEREFERENCE_ATOM: (None, unpack_dereference),
                  LIST_ATOM: (list, unpack_list),
                  SET_ATOM: (set, unpack_set),
                  DICT_ATOM: (dict, unpack_dict)}
