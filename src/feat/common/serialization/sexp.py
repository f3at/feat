from feat.interface.serialization import *

from . import base

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

REFERENCE_ATOM = "reference"
DEREFERENCE_ATOM = "dereference"


class Serializer(base.Serializer):
    '''Serialize any python structure into s-expression compatible
    with twisted.spread.jelly.'''

    def pack_unicode(self, value):
        return [UNICODE_ATOM, value.encode(UNICODE_FORMAT_ATOM)]

    def pack_bool(self, value):
        return [BOOL_ATOM, BOOL_TRUE_ATOM if value else BOOL_FALSE_ATOM]

    def pack_none(self, value):
        return [NONE_ATOM]

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


class Unserializer(base.Unserializer):
    '''Unserialize a structure serialized with L{sexp.Serializer}.'''

    ### Overridden Methods ###

    def unpack_data(self, data):
        vtype = type(data)

        # Just return simple immutable values as-is
        if vtype in (str, int, long, float):
            return data

        if vtype is not list:
            raise TypeError("Invalid input data for unserializer %s: %r"
                            % (type(self).__name__, data))

        type_name, values = data[0], data[1:]

        unpacker = self._simple_unpacker.get(type_name)
        if unpacker is not None:
            return unpacker(self, values)

        lookup = self._mutable_unpacker.get(type_name)
        if lookup is not None:
            unpacker, container_type = lookup
            container = container_type()
            return self.delay_unpacking(container, unpacker,
                                        self, container, values)

        # We assume it is an instance
        value, = values
        return self.restore_instance(type_name, value)

    ### Private Methods ###

    def unpack_unicode(self, data):
        value, = data
        if not isinstance(value, str):
            raise TypeError("Invalid %s value type: %r"
                            % (UNICODE_ATOM, value))
        return value.decode(UNICODE_FORMAT_ATOM)

    def unpack_bool(self, data):
        value, = data
        if value == BOOL_TRUE_ATOM:
            return True
        if value == BOOL_FALSE_ATOM:
            return False
        raise ValueError("Invalid %s value: %r" % (BOOL_ATOM, value))

    def unpack_none(self, data):
        if data:
            raise ValueError("Invalid %s packet" % (NONE_ATOM, ))
        return None

    def unpack_tuple(self, data):
        return tuple([self.unpack_data(d) for d in data])

    def unpack_reference(self, data):
        refid, value = data
        return self.restore_reference(refid, value)

    def unpack_dereference(self, data):
        refid, = data
        return self.restore_dereference(refid)

    def unpack_list(self, container, data):
        container.extend([self.unpack_data(d) for d in data])

    def unpack_set(self, container, data):
        container.update([self.unpack_data(d) for d in data])

    def unpack_dict(self, container, data):
        container.update([(self.unpack_data(k), self.unpack_data(v))
                          for k, v in data])

    _simple_unpacker = {UNICODE_ATOM: unpack_unicode,
                        BOOL_ATOM: unpack_bool,
                        NONE_ATOM: unpack_none,
                        TUPLE_ATOM: unpack_tuple,
                        REFERENCE_ATOM: unpack_reference,
                        DEREFERENCE_ATOM: unpack_dereference}

    _mutable_unpacker = {LIST_ATOM: (unpack_list, list),
                         SET_ATOM: (unpack_set, set),
                         DICT_ATOM: (unpack_dict, dict)}
