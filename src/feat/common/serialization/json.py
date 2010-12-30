from __future__ import absolute_import

import json as json

from feat.common import reflect
from feat.interface.serialization import *

from . import base


TUPLE_ATOM = "_tuple"
BYTES_ATOM = "_bytes"
BYTES_ENCODING = "BASE64"
ENCODED_ATOM = "_enc"
SET_ATOM = "_set"
ENUM_ATOM = "_enum"
TYPE_ATOM = "_type"
EXTERNAL_ATOM = "_ext"
REFERENCE_ATOM = "_ref"
DEREFERENCE_ATOM = "_deref"

INSTANCE_TYPE_ATOM = "_type"
INSTANCE_STATE_ATOM = "_state"

DEFAULT_ENCODING = "UTF8"
ALLOWED_CODECS = set(["UTF8", "UTF-8", "utf8"])

JSON_CONVERTER_CAPS = set([Capabilities.int_values,
                           Capabilities.enum_values,
                           Capabilities.float_values,
                           Capabilities.str_values,
                           Capabilities.unicode_values,
                           Capabilities.bool_values,
                           Capabilities.none_values,
                           Capabilities.tuple_values,
                           Capabilities.list_values,
                           Capabilities.set_values,
                           Capabilities.dict_values,
                           Capabilities.type_values,
                           Capabilities.instance_values,
                           Capabilities.external_values,
                           Capabilities.str_keys,
                           Capabilities.circular_references,
                           Capabilities.meta_types])

JSON_FREEZER_CAPS = JSON_CONVERTER_CAPS \
                    | set([Capabilities.function_values,
                           Capabilities.method_values])


class Serializer(base.Serializer):

    pack_dict = dict

    def __init__(self, indent=None, separators=None, externalizer=None):
        base.Serializer.__init__(self, converter_caps=JSON_CONVERTER_CAPS,
                                 freezer_caps=JSON_FREEZER_CAPS,
                                 externalizer=externalizer)
        self._indent = indent
        self._separators = separators

    ### Overridden Methods ###

    def post_convertion(self, data):
        return json.dumps(data, indent=self._indent,
                          separators=self._separators)

    def flatten_key(self, key, caps, freezing):
        if not isinstance(key, str):
            raise TypeError("Serializer %s is not capable of serializing "
                            "non-string dictionary keys: %r"
                            % (reflect.canonical_name(self), key))
        # Flatten it as unicode by using the selected encoding
        return self.pack_unicode, key.decode(DEFAULT_ENCODING)

    def pack_tuple(self, data):
        # JSON do not support tuple so we just fake it
        return [TUPLE_ATOM] + data

    def pack_str(self, data):
        # we try to decode the string from default encoding
        try:
            value = data.decode(DEFAULT_ENCODING)
            return [ENCODED_ATOM, DEFAULT_ENCODING, value]
        except UnicodeDecodeError:
            # if it fail store it as base64 encoded bytes
            return [BYTES_ATOM, data.encode(BYTES_ENCODING).strip()]

    def pack_set(self, data):
        return [SET_ATOM] + data

    def pack_enum(self, data):

        return [ENUM_ATOM, reflect.canonical_name(data) + "." + data.name]

    def pack_type(self, data):
        return [TYPE_ATOM, reflect.canonical_name(data)]

    def pack_external(self, data):
        return [EXTERNAL_ATOM] + data

    def pack_instance(self, data):
        type_name, snapshot = data

        if isinstance(snapshot, dict):
            result = dict(snapshot) # Copy the dict to not modify the original
            assert INSTANCE_TYPE_ATOM not in result
            assert INSTANCE_STATE_ATOM not in result
            result[INSTANCE_TYPE_ATOM] = type_name
            return result

        return {INSTANCE_TYPE_ATOM: type_name,
                INSTANCE_STATE_ATOM: snapshot}

    def pack_reference(self, data):
        return [REFERENCE_ATOM] + data

    def pack_dereference(self, data):
        return [DEREFERENCE_ATOM, data]

    def pack_frozen_instance(self, data):
        snapshot, = data
        return snapshot

    def pack_frozen_function(self, data):
        return reflect.canonical_name(data)

    def pack_frozen_method(self, data):
        return reflect.canonical_name(data)


class Unserializer(base.Unserializer):

    pass_through_types = set([str, unicode, int, float, bool, type(None)])

    def __init__(self, registry=None, externalizer=None):
        base.Unserializer.__init__(self, converter_caps=JSON_CONVERTER_CAPS,
                                   registry=registry,
                                   externalizer=externalizer)

    ### Overridden Methods ###

    def pre_convertion(self, data):
        return json.loads(data)

    def analyse_data(self, data):
        if isinstance(data, dict):
            if INSTANCE_TYPE_ATOM in data:
                return None, Unserializer.unpack_instance
            return dict, Unserializer.unpack_dict

        if isinstance(data, list):
            default = list, Unserializer.unpack_list
            if not data:
                # Empty list
                return default
            key = data[0]
            if isinstance(key, unicode):
                return self._list_unpackers.get(key, default)
            # Just a list
            return default

    ### Private Methods ###

    def unpack_external(self, data):
        _, identifier = data
        return self.restore_external(identifier)

    def unpack_instance(self, data):
        type_name = data.pop(INSTANCE_TYPE_ATOM)
        if INSTANCE_STATE_ATOM in data:
            snapshot = data.pop(INSTANCE_STATE_ATOM)
        else:
            snapshot = data
        return self.restore_instance(type_name, snapshot)

    def unpack_reference(self, data):
        _, refid, value = data
        return self.restore_reference(refid, value)

    def unpack_dereference(self, data):
        _, refid = data
        return self.restore_dereference(refid)

    def unpack_enum(self, data):
        _, full_name = data
        parts = full_name.encode(DEFAULT_ENCODING).split('.')
        type_name = ".".join(parts[:-1])
        enum = self.restore_type(type_name)
        return enum.get(parts[-1])

    def unpack_type(self, data):
        _, type_name = data
        return self.restore_type(type_name)

    def unpack_encoded(self, data):
        _, codec, bytes = data
        if codec not in ALLOWED_CODECS:
            raise ValueError("Unsupported codec: %r" % codec)
        return bytes.encode(codec)

    def unpack_bytes(self, data):
        _, bytes = data
        return bytes.decode(BYTES_ENCODING)

    def unpack_tuple(self, data):
        return tuple([self.unpack_data(d) for d in data[1:]])

    def unpack_list(self, container, data):
        container.extend([self.unpack_data(d) for d in data])

    def unpack_set(self, container, data):
        container.update(self.unpack_unordered_values(data[1:]))

    def unpack_dict(self, container, data):
        items = [(k.encode(DEFAULT_ENCODING), v)for k, v in data.iteritems()]
        container.update(self.unpack_unordered_pairs(items))

    _list_unpackers = {u"_bytes": (None, unpack_bytes),
                       u"_enc": (None, unpack_encoded),
                       u"_enum": (None, unpack_enum),
                       u"_type": (None, unpack_type),
                       u"_tuple": (None, unpack_tuple),
                       u"_set": (set, unpack_set),
                       u"_ext": (None, unpack_external),
                       u"_ref": (None, unpack_reference),
                       u"_deref": (None, unpack_dereference)}


class PaisleyUnserializer(Unserializer):
    '''Hack to cope with Paisley performing json.loads on its own.'''

    def pre_convertion(self, data):
        return data