from zope.interface import implements

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


class Unserializer(base.Unserializer):
    '''Unserialize a structure serialized with L{pytree.Serializer}.
    The complexity in unserializing from python object tree is that
    set and dictionary are not ordered. Because of that we cannot
    ensure references are processed before being dereferenced.
    The base class raises DelayUnpacking exception when an unknown
    reference got dereferenced, so unpacking '''

    ### Overridden Methods ###

    def unpack_data(self, data):
        vtype = type(data)

        # Just return simple immutable values as-is
        if vtype in (str, unicode, int, long, float, bool, type(None)):
            return data

        # Special case for tuples
        if vtype == tuple:
            return tuple([self.unpack_data(d) for d in data])

        # For mutable types, we create an empty instance and return it
        # to break the deserialization chain in order to handle circular
        # references, but we register a callback to continue later on.
        unpacker = self._lookup_unpacker.get(vtype)
        if unpacker is not None:
            # First argument is self because the functions are not bound
            # and the container is specified two time once for the base class
            # and once for the function call argument
            container = vtype()
            return self.delay_unpacking(container, unpacker,
                                        self, container, data)

        # Handle references, dereferences and instances
        # We want to be compatible with all implementations
        # of the interface so we cannot use lookup table
        if IInstance.providedBy(data):
            return self.restore_instance(data.type_name, data.snapshot)

        if IDereference.providedBy(data):
            return self.restore_dereference(data.refid)

        if IReference.providedBy(data):
            return self.restore_reference(data.refid, data.value)

        raise TypeError("Type %s not supported by unserializer %s"
                        % (type(data).__name__, type(self).__name__))

    ### Private Methods ###

    def unpack_list(self, container, data):
        container.extend([self.unpack_data(d) for d in data])

    def unpack_set(self, container, data):
        '''Unpacking sets is a pain not quite like dictionaries but not far.
        See unpack_dict() doc for more info.'''

        values = list(data)

        # Try to unpack items more than one time to resolve cross references
        max_loop = 3
        while values and max_loop:
            next_values = []
            for value_data in values:
                try:
                    # try unpacking the value
                    value = self.unpack_data(value_data)
                except base.DelayPacking:
                    # If it is delayed keep it for later
                    next_values.append(value_data)
                    continue
                container.add(value)
            values = next_values
            max_loop -= 1

        if values:
            # Not all items were resolved
            raise base.DelayPacking()

    def unpack_dict(self, container, data):
        '''Unpacking dictionary is a pain.
        because item order change between packing and unpacking.
        So if unpacking an item fail because of unknown dereference,
        we must keep it aside, continue unpacking the other items
        and continue later.'''

        items = [(False, k, v) for k, v in data.iteritems()]

        # Try to unpack items more than one time to resolve cross references
        max_loop = 3
        while items and max_loop:
            next_items = []
            for key_unpacked, key_data, value_data in items:
                if key_unpacked:
                    key = key_data
                else:
                    try:
                        # Try unpacking the key
                        key = self.unpack_data(key_data)
                    except base.DelayPacking:
                        # If it is delayed keep it for later
                        next_items.append((False, key_data, value_data))
                        continue

                try:
                    # try unpacking the value
                    value = self.unpack_data(value_data)
                except base.DelayPacking:
                    # If it is delayed keep it for later
                    next_items.append((True, key, value_data))
                    continue

                # Update the container with the unpacked value and key
                container[key] = value
            items = next_items
            max_loop -= 1

        if items:
            # Not all items were resolved
            raise base.DelayPacking()

    _lookup_unpacker = {list: unpack_list,
                        set: unpack_set,
                        dict: unpack_dict}
