from zope.interface import implements

from feat.common import enum, reflect
from feat.interface.serialization import *

from . import base


class Instance(object):
    '''Used by TreeSerializer to encapsulate ISerializable instances.
    Implements L{IInstance} and can be compared for equality.'''

    implements(IInstance)

    __slots__ = ("type_name", "snapshot")

    @classmethod
    def _build(cls, data):
        type_name, snapshot = data
        return cls(type_name, snapshot)

    def __init__(self, type_name, snapshot):
        self.type_name = type_name
        self.snapshot = snapshot

    def __repr__(self):
        return "<Instance %s: %r>" % (self.type_name, self.snapshot)

    def __eq__(self, other):
        if not isinstance(other, Instance):
            return NotImplemented
        return (self.type_name == other.type_name
                and self.snapshot == other.snapshot)

    def __ne__(self, other):
        return not self.__eq__(other)


class Reference(object):
    '''Used by TreeSerializer to encapsulate references.
    Can be compared for equality and hashed if the referenced
    value is hashable. Implements L{IReference}.'''

    implements(IReference)

    __slots__ = ("refid", "value")

    @classmethod
    def _build(cls, data):
        refid, value = data
        return cls(refid, value)

    def __init__(self, refid, value):
        self.refid = refid
        self.value = value

    def __repr__(self):
        return "<Reference %s: %r>" % (self.refid, self.value)

    def __hash__(self):
        # Make references hashable to be able to use them as dict key
        return hash(self.refid) ^ hash(self.value)

    def __eq__(self, other):
        if not isinstance(other, Reference):
            return NotImplemented
        return (self.refid == other.refid
                and self.value == other.value)

    def __ne__(self, other):
        return not self.__eq__(other)


class Dereference(object):
    '''Used by TreeSerializer to encapsulate a dereference to a previous
    referenced value. Can be compared for equality and hashed.
    Implements L{IDereference}.'''

    implements(IDereference)

    __slots__ = ("refid", )

    def __init__(self, refid):
        self.refid = refid

    def __repr__(self):
        return "<Dereference %s>" % self.refid

    def __hash__(self):
        # Make dereferences hashable to be able to use them as dict key
        return hash(self.refid)

    def __eq__(self, other):
        if not isinstance(other, Dereference):
            return NotImplemented
        return self.refid == other.refid

    def __ne__(self, other):
        return not self.__eq__(other)


class Serializer(base.Serializer):
    '''Serialize any python structure to a tree of basic python types,
    L{IInstance}, L{IReference} and L{IDereference}.

    Object have to implement L{ISerializable} to be serialized.

    Examples::

        >> a = [1, 2, 3]
        >> b = [4, 5, 6]
        >> c = ['X', a, 'Y', b, 'Z', a]
        >> print TreeSerializer().convert(c)
        ['X', <Reference 1: [1, 2, 3]>, 'Y', [4, 5, 6], 'Z', <Derefence: 1>]

        >> o = Serializable()
        >> o.foo = 42
        >> print TreeSerializer().convert(o)
        <Instance feat.common.serialization.Serializable: {"foo": 42}>

    '''

    pack_tuple = tuple
    pack_set = set
    pack_dict = dict
    pack_instance = Instance._build
    pack_reference = Reference._build
    pack_dereference = Dereference

    def pack_frozen_instance(self, value):
        content, = value
        return content

    def pack_frozen_function(self, value):
        return reflect.canonical_name(value)

    def pack_frozen_method(self, value):
        return reflect.canonical_name(value)


class Unserializer(base.Unserializer):
    '''Unserialize a structure serialized with L{pytree.Serializer}.
    The complexity in unserializing from python object tree is that
    set and dictionary are not ordered. Because of that we cannot
    ensure references are processed before being dereferenced.
    The base class raises DelayUnpacking exception when an unknown
    reference got dereferenced, so unpacking '''

    pass_through_types = set([str, unicode, int, long,
                              float, bool, type(None),
                              enum.MetaEnum, type])

    ### Overridden Methods ###

    def analyse_data(self, data):
        data_type = type(data)

        lookup = self._unpackers.get(data_type)
        if lookup is not None:
            return lookup

        # Handle references, dereferences and instances
        # We want to be compatible with all implementations
        # of the interface so we cannot use lookup table

        if IInstance.providedBy(data):
            return None, Unserializer.unpack_instance

        if IDereference.providedBy(data):
            return None, Unserializer.unpack_dereference

        if IReference.providedBy(data):
            return None, Unserializer.unpack_reference

    ### Private Methods ###

    def unpack_instance(self, data):
        return self.restore_instance(data.type_name, data.snapshot)

    def unpack_reference(self, data):
        return self.restore_reference(data.refid, data.value)

    def unpack_dereference(self, data):
        return self.restore_dereference(data.refid)

    def unpack_tuple(self, data):
        return tuple([self.unpack_data(d) for d in data])

    def unpack_list(self, container, data):
        container.extend([self.unpack_data(d) for d in data])

    def unpack_set(self, container, data):
        container.update(self.unpack_unordered_values(data))

    def unpack_dict(self, container, data):
        container.update(self.unpack_unordered_pairs(data.iteritems()))

    _unpackers = {tuple: (None, unpack_tuple),
                  list: (list, unpack_list),
                  set: (set, unpack_set),
                  dict: (dict, unpack_dict)}
