import copy

from zope.interface import implements

from feat.common import decorator, enum, adapter, reflect
from feat.interface.serialization import *

DEFAULT_CAPABILITIES = set([Capabilities.int_values,
                            Capabilities.enum_values,
                            Capabilities.long_values,
                            Capabilities.float_values,
                            Capabilities.str_values,
                            Capabilities.unicode_values,
                            Capabilities.bool_values,
                            Capabilities.none_values,
                            Capabilities.tuple_values,
                            Capabilities.list_values,
                            Capabilities.set_values,
                            Capabilities.dict_values,
                            Capabilities.instance_values,
                            Capabilities.type_values,
                            Capabilities.int_keys,
                            Capabilities.enum_keys,
                            Capabilities.long_keys,
                            Capabilities.float_keys,
                            Capabilities.str_keys,
                            Capabilities.unicode_keys,
                            Capabilities.bool_keys,
                            Capabilities.none_keys,
                            Capabilities.tuple_keys,
                            Capabilities.type_keys,
                            Capabilities.circular_references,
                            Capabilities.meta_types])


@decorator.simple_class
def register(restorator):
    '''Register a class as a L{IRestorator} in the default global registry.'''
    global _global_registry
    _global_registry.register(restorator)
    return restorator


@adapter.register(object, ISnapshotable)
class SnapshotableAdapter(object):
    '''Make any object a L{ISnapshotable} that return itself as snapshot.'''

    implements(ISnapshotable)

    def __init__(self, value):
        self.value = value

    ### ISnapshotable Methods ###

    def snapshot(self):
        return self.value


class MetaSnapshotable(type):

    def __init__(cls, name, bases, dct):
        if "type_name" not in dct:
            type_name = dct["__module__"] + "." + name
            setattr(cls, "type_name", type_name)
        super(MetaSnapshotable, cls).__init__(name, bases, dct)


class Snapshotable(object):
    '''Simple L{ISnapshotable} that snapshot the instance attributes
    not starting by an underscore. If the class attribute type_name
    is not defined, the canonical name of the class is used.'''

    __metaclass__ = MetaSnapshotable

    implements(ISnapshotable)

    ### ISnapshotable Methods ###

    def snapshot(self):
        return dict([(k, v)
                     for k, v in self.__dict__.iteritems()
                     if isinstance(k, str) and not k.startswith('_')])


class MetaSerializable(MetaSnapshotable):

    implements(IRestorator)


class Serializable(Snapshotable):
    '''Simple L{ISerializable} that serialize and restore the full instance
    dictionary. If the class attribute type_name is not defined, the canonical
    name of the class is used.'''

    __metaclass__ = MetaSerializable

    implements(ISerializable)

    type_name = None

    @classmethod
    def prepare(cls):
        return cls.__new__(cls)

    @classmethod
    def restore(cls, snapshot):
        instance = cls.prepare()
        instance.recover(snapshot)
        return instance

    def recover(self, snapshot):
        self.__dict__.update(snapshot)

    def restored(self):
        pass


class Registry(object):
    '''Keep track of L{IRestorator}. Used by unserializers.'''

    implements(IRegistry)

    def __init__(self):
        self._registry = {} # {TYPE_NAME: IRestorator}


    ### IRegistry Methods ###

    def register(self, restorator):
        r = IRestorator(restorator)
        self._registry[r.type_name] = r

    def lookup(self, type_name):
        return self._registry.get(type_name)


@decorator.simple_function
def referenceable(method):
    '''Used in BaseSerializer and its sub-classes to flatten referenceable
    values. Hide the reference handling from sub-classes.
    For example, to make strings referenceable in a sub-class only use
    this decorator with decorate flatten_str().'''

    def wrapper(self, value):
        deref = self._prepare(value)
        if deref is not None:
            return deref
        packer, data = method(self, value)
        return self._preserve(value, packer, data)

    return wrapper


class Serializer(object):
    '''Base class for serializers handling references.

    A post converter can be specified at construction time to be chained.
    If specified, the output of this converter will be passed to it
    and it's result will be returned instead. It could be used to format
    the serialized data to a binary stream.

    The serialization is done in two pass. First the structure is flattened
    to a list of list where the first element is None or a function used
    to pack the following values::

      "spam" -> [pack_str, "spam"]
      u"spam" -> [pack_unicode, u"spam"]
      42 -> [pack_int, 42]
      0.1 -> [pack_float, 0.1]
      2L -> [pack_long, 2L]
      (1, 2, 3) -> [pack_tuple, [1, 2, 3]]
      [1, 2, 3] -> [pack_list, [1, 2, 3]]
      set([1, 2, 3]) -> [pack_set, [1, 2, 3]]
      {1: 2, 3: 4} -> [pack_dict, [[pack_item, 1, 2], [pack_item, 3, 4]]]

    Then the lists are packed using the packing function if specified,
    starting from the leaf up to the root. For example, the following
    flattened structure::

      [pack_list, [[pack_int, 42], [pack_list, [pack_int, 18]]]]

    will be packed the following way::

      pack_list([pack_int(42), pack_list([pack_int(18)])])

    This class handle references by encapsulating values referenced multiple
    times inside a special "reference" value that use it's own packing
    function, and then use a special "dereference" value when later
    referenced::

      > a = [1]
      > b = [a, a]
      > serialize(b)
      [pack_list, [[pack_reference, [1, [pack_list, [pack_int, 1]]]],
      [pack_dereference, 1]]]

    Sub classes can override the packing functions used for each types.

    NOTE: because the flatten methods lookup table is done at class
    declaration time, overriding most of flatten_* method will not work.
    Only flatten_value, flatten_key, flatten_item, flatten_unknown,
    flatten_instance and flatten_frozen_instance can be overridden
    safely by subclasses. In case overriding other flatten_* method
    would be needed in the future, the lookup table initialization
    should be moved to the constructor and self should not be passed anymore
    as the first parameter because the function would be then bound.

    #FIXME: Add datetime types datetime, date, time and timedelta

    '''

    implements(IFreezer, IConverter)

    pack_str = None
    pack_unicode = None
    pack_int = None
    pack_enum = None
    pack_long = None
    pack_float = None
    pack_bool = None
    pack_none = None
    pack_tuple = None
    pack_list = None
    pack_item = None
    pack_dict = None
    pack_type = None
    pack_type_name = None
    pack_instance = None
    pack_reference = None
    pack_dereference = None
    pack_frozen_instance = None

    def __init__(self, capabilities=None, post_converter=None):
        self.capabilities = capabilities or DEFAULT_CAPABILITIES
        self._post_converter = post_converter and IConverter(post_converter)
        self.reset()

    ### IFreezer Methods ###

    def freeze(self, data):
        # Set the instance type requirements to ISnapshotable
        # because we don't need unserialization guarantee
        self._freezing = True
        return self._convert(data)

    ### IConverter Methods ###

    def convert(self, data):
        # Set the instance type requirements to ISerializable
        # because we don't want to enforce the result to be unserializable
        self._freezing = False
        return self._convert(data)

    ### Protected Methods ###

    def check_capabilities(self, cap, *args):
        assert len(args) <= 1, "maximum of 1 extra parameter"
        if args:
            extra = ": %r" % args
        else:
            extra = ""

        if cap not in self.capabilities:
            raise ValueError("Serializer %s do not support %s%s"
                             % (reflect.canonical_name(self), cap.name, extra))

    def pack_value(self, data):
        if not isinstance(data, (list, tuple)):
            return data
        packer, value = data
        if isinstance(value, list):
            value = [self.pack_value(d) for d in value]
        if packer is not None:
            return packer(value)
        return value

    def flatten_value(self, value):
        vtype = type(value)
        default = Serializer.flatten_unknown_value
        return self._value_lookup.get(vtype, default)(self, value)

    def flatten_key(self, value):
        vtype = type(value)
        default = Serializer.flatten_unknown_key
        return self._key_lookup.get(vtype, default)(self, value)

    def post_convertion(self, data):
        if self._post_converter:
            return self._post_converter.convert(data)
        return data

    def reset(self):
        self._freezing = False # If we are freezing or serializing
        self._preserved = {} # {OBJ_ID: FLATTENED_STRUCTURE}
        self._refids = {} # {OBJ_ID: REFERENCE_ID}
        self._references = {} # {OBJ_ID: REFERENCE_CONTAINER}
        self._memory = []
        self._refid = 0

    def flatten_unknown_value(self, value):
        # Flatten enums
        if isinstance(value, enum.Enum):
            return self.flatten_enum_value(value)

        # Flatten types
        if isinstance(value, type):
            return self.flatten_type_value(value)

        # Checks if value support the current required protocol
        # Could be ISnapshotable or ISerializable
        if self._freezing:
            if ISnapshotable.providedBy(value):
                return self.flatten_frozen_instance(ISnapshotable(value))
        else:
            if ISerializable.providedBy(value):
                return self.flatten_instance(ISerializable(value))

        raise TypeError("Type %s values not supported by serializer %s"
                        % (type(value).__name__,
                           reflect.canonical_name(self)))

    def flatten_unknown_key(self, value):
        # Flatten enums
        if isinstance(value, enum.Enum):
            return self.flatten_enum_key(value)

        # Flatten types
        if isinstance(value, type):
            return self.flatten_type_key(value)

        # Instances are not supported in keys
        raise TypeError("Type %s keys not supported by serializer %s"
                        % (type(value).__name__,
                           reflect.canonical_name(self)))

    def flatten_item(self, value):
        key, value = value
        return self.pack_item, [self.flatten_key(key),
                                self.flatten_value(value)]

    def flatten_str_value(self, value):
        self.check_capabilities(Capabilities.str_values, value)
        return self.pack_str, value

    def flatten_unicode_value(self, value):
        self.check_capabilities(Capabilities.unicode_values, value)
        return self.pack_unicode, value

    def flatten_int_value(self, value):
        self.check_capabilities(Capabilities.int_values, value)
        return self.pack_int, value

    def flatten_long_value(self, value):
        self.check_capabilities(Capabilities.long_values, value)
        return self.pack_long, value

    def flatten_float_value(self, value):
        self.check_capabilities(Capabilities.float_values, value)
        return self.pack_float, value

    def flatten_none_value(self, value):
        self.check_capabilities(Capabilities.none_values, value)
        return self.pack_none, value

    def flatten_bool_value(self, value):
        self.check_capabilities(Capabilities.bool_values, value)
        return self.pack_bool, value

    def flatten_enum_value(self, value):
        self.check_capabilities(Capabilities.enum_values, value)
        return self.pack_enum, value

    def flatten_type_value(self, value):
        self.check_capabilities(Capabilities.type_values, value)
        return self.pack_type, value

    @referenceable
    def flatten_tuple_value(self, value):
        self.check_capabilities(Capabilities.tuple_values, value)
        return self.pack_tuple, [self.flatten_value(v) for v in value]

    @referenceable
    def flatten_list_value(self, value):
        self.check_capabilities(Capabilities.list_values, value)
        return self.pack_list, [self.flatten_value(v) for v in value]

    @referenceable
    def flatten_set_value(self, value):
        self.check_capabilities(Capabilities.set_values, value)
        return self.pack_set, [self.flatten_value(v) for v in value]

    @referenceable
    def flatten_dict_value(self, value):
        self.check_capabilities(Capabilities.dict_values, value)
        return self.pack_dict, [self.flatten_item(i)
                                for i in value.iteritems()]

    def flatten_str_key(self, value):
        self.check_capabilities(Capabilities.str_keys, value)
        return self.pack_str, value

    def flatten_unicode_key(self, value):
        self.check_capabilities(Capabilities.unicode_keys, value)
        return self.pack_unicode, value

    def flatten_int_key(self, value):
        self.check_capabilities(Capabilities.int_keys, value)
        return self.pack_int, value

    def flatten_long_key(self, value):
        self.check_capabilities(Capabilities.long_keys, value)
        return self.pack_long, value

    def flatten_float_key(self, value):
        self.check_capabilities(Capabilities.float_keys, value)
        return self.pack_float, value

    def flatten_none_key(self, value):
        self.check_capabilities(Capabilities.none_keys, value)
        return self.pack_none, value

    def flatten_bool_key(self, value):
        self.check_capabilities(Capabilities.bool_keys, value)
        return self.pack_bool, value

    def flatten_enum_key(self, value):
        self.check_capabilities(Capabilities.enum_keys, value)
        return self.pack_enum, value

    def flatten_type_key(self, value):
        self.check_capabilities(Capabilities.type_keys, value)
        return self.pack_type, value

    @referenceable
    def flatten_tuple_key(self, value):
        self.check_capabilities(Capabilities.tuple_keys, value)
        return self.pack_tuple, [self.flatten_value(v) for v in value]

    @referenceable
    def flatten_frozen_instance(self, value):
        self.check_capabilities(Capabilities.instance_values, value)
        return self.pack_frozen_instance, self.flatten_value(value.snapshot())

    @referenceable
    def flatten_instance(self, value):
        self.check_capabilities(Capabilities.instance_values, value)
        return self.pack_instance, [[self.pack_type_name, value.type_name],
                                     self.flatten_value(value.snapshot())]

    ### Setup lookup tables ###

    _value_lookup = {tuple: flatten_tuple_value,
                     list: flatten_list_value,
                     set: flatten_set_value,
                     dict: flatten_dict_value,
                     str: flatten_str_value,
                     unicode: flatten_unicode_value,
                     int: flatten_int_value,
                     long: flatten_long_value,
                     float: flatten_float_value,
                     bool: flatten_bool_value,
                     type(None): flatten_none_value}

    _key_lookup = {tuple: flatten_tuple_key,
                   str: flatten_str_key,
                   unicode: flatten_unicode_key,
                   int: flatten_int_key,
                   long: flatten_long_key,
                   float: flatten_float_key,
                   bool: flatten_bool_key,
                   type(None): flatten_none_key}

    ### Private Methods ###

    def _convert(self, data):
        try:
            # Flatten the value to the list-only format with packer function
            flattened = self.flatten_value(data)
            # Pack all the value with there own packer functions
            packed = self.pack_value(flattened)
            # Post-convert the data if a convert was specified
            return self.post_convertion(packed)
        finally:
            # Reset the state to cleanup all references
            self.reset()

    def _next_refid(self):
        self._refid += 1
        return self._refid

    def _prepare(self, value):
        ident = id(value)
        # Check if already preserved
        if ident in self._preserved:
            # Already preserved so we should return a dereference
            if ident in self._refids:
                # Already referenced, just use the reference identifier
                refid = self._refids[ident]
            else:
                # First dereference, we should mutate the original value
                # to a reference using the preserved list
                reference = self._preserved[ident]
                # Copy the original value before mutating
                new_value = copy.copy(reference)
                # Get a new reference identifier
                refid = self._next_refid()
                # Mutate the preserved list
                reference[:] = self.pack_reference, [refid, new_value]
                # Remember the reference identifier for this value
                self._refids[ident] = refid
                # Keep the reference to be able to return it from _preserv()
                # in case of cycle references
                self._references[ident] = reference
                # Update the original to be able to update
                # the reference value in-place
                self._preserved[ident] = new_value

            # Return a dereference
            return [self.pack_dereference, refid]

        # Preserve the value container to be able to mutate it to a reference
        self._preserved[ident] = []
        return None

    def _preserve(self, value, packer, data):
        ident = id(value)
        # Keep a reference to the value to prevent it to be garbage-collected.
        # If it was, a different value with the same id could appear
        # and the reference system would be corrupted.
        self._memory.append(value)
        # Retrieve the value container
        container = self._preserved[ident]
        # Set the value in place, even if it has been referenced
        container[:] = packer, data
        # If the value has been referenced, return the reference
        if ident in self._references:
            return self._references[ident]
        # Otherwise return the value itself
        return container


class DelayPacking(Exception):
    '''Exception raised when unpacking a dereference to an unknown
    reference. This allows to delay unpacking of mutable object
    containing dereferences.'''


class Unserializer(object):
    '''Base class for unserializers. It handle delayed unpacking
    and instance restoration to resolve circular references.
    If no registry instance is specified when created, the default
    global registry will be used.

    A pre-converter can be specified at creation time, if so the
    data will be first converted by the given converter and then
    the result will be unserialized. Used to parse data before
    unserializing.
    '''

    implements(IConverter)

    pass_through_types = ()

    def __init__(self, capabilities=None, pre_converter=None, registry=None):
        global _global_registry
        self.capabilities = capabilities or DEFAULT_CAPABILITIES
        self._pre_converter = pre_converter and IConverter(pre_converter)
        self._registry = IRegistry(registry) if registry else _global_registry
        self.reset()

    ### IConverter Methods ###

    def convert(self, data):
        try:
            # Pre-convert the data if a convertor was specified
            converted = self.pre_convertion(data)
            # Unpack the first level of values
            unpacked = self.unpack_data(converted)
            # Continue unpacking level by level
            self.finish_unpacking()
            # Should be finished by now
            return unpacked
        finally:
            # Reset the state to cleanup all references
            self.reset()

    ### Protected Methods ###

    def pre_convertion(self, data):
        if self._pre_converter is not None:
            return self._pre_converter.convert(data)
        return data

    def reset(self):
        self._references = {} # {REFERENCE_ID: (DATA_ID, OBJECT)}
        self._pending = [] # Pendings unpacking
        self._instances = [] # [(INSTANCE, SNAPSHOT)]
        self._delayed = 0 # If we are in a delayable unpacking

    def unpack_data(self, data):

        # Just return pass-through types,
        # support sub-classed base types and metaclasses
        if set(type(data).__mro__) & self.pass_through_types:
            return data

        analysis = self.analyse_data(data)

        if analysis is None:
            raise TypeError("Type %s not supported by unserializer %s"
                            % (type(data).__name__,
                               reflect.canonical_name(self)))

        constructor, unpacker = analysis

        # Unpack the mutable containers that provides constructor
        if constructor is not None:
            # The container is specified two time once for the base class
            # and once for the function call argument
            container = constructor()
            return self.delayed_unpacking(container, unpacker,
                                          self, container, data)

        return unpacker(self, data)

    def delayed_unpacking(self, container, fun, *args, **kwargs):
        '''Should be used when unpacking mutable values.
        This allows circular references resolution by pausing serialization.'''
        try:
            self._delayed += 1
            try:
                fun(*args, **kwargs)
                return container
            except DelayPacking:
                continuation = (fun, args, kwargs)
                self._pending.append(continuation)
                return container
        finally:
            self._delayed -= 1

    def finish_unpacking(self):
        while self._pending:
            fun, args, kwargs = self._pending.pop(0)
            fun(*args, **kwargs)

        # Initialize the instance in creation order
        for instance, snapshot in self._instances:
            instance.recover(snapshot)

        # Calls the instances post restoration callback in reversed order
        # in an intent to reduce the possibilities of instances relying
        # on there references being fully restored when called.
        # This should not be relied on anyway.
        for instance, _ in reversed(self._instances):
            instance.restored()

    def restore_type(self, type_name):
        value = reflect.named_object(type_name)
        if issubclass(value, type):
            raise ValueError("type %r unserialized to something that "
                             "isn't a type: %r" % (type_name, value))
        return value

    def restore_instance(self, type_name, data):
        # Lookup the registry for a IRestorator
        restorator = self._registry.lookup(type_name)
        if restorator is None:
            raise TypeError("Type %s not supported by unserializer %s"
                            % (type_name, reflect.canonical_name(self)))
        # Prepare the instance for recovery
        instance = restorator.prepare()
        if instance is None:
            # Immutable type, we can't delay restoration
            snapshot = self.unpack_data(data)
            return restorator.restore(snapshot)

        # Delay the instance restoration for later to handle circular refs
        return self.delayed_unpacking(instance,
                                      self._continue_restoring_instance,
                                      instance, data)

    def restore_reference(self, refid, data):
        if refid in self._references:
            # This is because of DelayUnpacking exception, reference
            # can be registered multiple times
            data_id, value = self._references[refid]
            if data_id == id(data):
                return value
            raise ValueError("Multiple references found with "
                             "the same identifier: %s" % refid)
        value = self.unpack_data(data)
        self._references[refid] = (id(data), value)
        return value

    def restore_dereference(self, refid):
        if refid not in self._references:
            # Dereference to an unknown reference
            if self._delayed > 0:
                # If we unpacking can be delayed because we are unpacking
                # a mutable object just delay the unpacking for later
                raise DelayPacking()
            raise ValueError("Dereferencing of yet unknown reference: %s"
                             % refid)
        _data_id, value = self._references[refid]
        return value

    def unpack_unordered_values(self, values):
        '''Unpack an unordered list of values taking DelayPacking
        exceptions into account to resolve circular references .
        Used to unpack set values when order is not guaranteed by
        the serializer. See unpack_unordered_pairs().'''

        values = list(values) # To support iterators
        result = []

        # Try to unpack values more than one time to resolve cross references
        max_loop = 2
        while values and max_loop:
            next_values = []
            for value_data in values:
                try:
                    # try unpacking the value
                    value = self.unpack_data(value_data)
                except DelayPacking:
                    # If it is delayed keep it for later
                    next_values.append(value_data)
                    continue
                result.append(value)
            values = next_values
            max_loop -= 1

        if values:
            # Not all items were resolved
            raise DelayPacking()

        return result

    def unpack_unordered_pairs(self, pairs):
        '''Unpack an unordered list of value pairs taking DelayPacking
        exceptions into account to resolve circular references .
        Used to unpack dictionary items when the order is not guarennteed
        by the serializer. When item order change between packing
        and unpacking, references are not guaranteed to appear before
        dereferences anymore. So if unpacking an item fail because
        of unknown dereference, we must keep it aside, continue unpacking
        the other items and continue later.'''

        items = [(False, k, v) for k, v in pairs]
        result = []

        # Try to unpack items more than one time to resolve cross references
        max_loop = 2
        while items and max_loop:
            next_items = []
            for key_unpacked, key_data, value_data in items:
                if key_unpacked:
                    key = key_data
                else:
                    try:
                        # Try unpacking the key
                        key = self.unpack_data(key_data)
                    except DelayPacking:
                        # If it is delayed keep it for later
                        next_items.append((False, key_data, value_data))
                        continue

                try:
                    # try unpacking the value
                    value = self.unpack_data(value_data)
                except DelayPacking:
                    # If it is delayed keep it for later
                    next_items.append((True, key, value_data))
                    continue

                # Update the container with the unpacked value and key
                result.append((key, value))
            items = next_items
            max_loop -= 1

        if items:
            # Not all items were resolved
            raise DelayPacking()

        return result

    ### Virtual Methods, to be Overridden by Sub-Classes ###

    def analyse_data(self, data):
        '''Analyses the data provided and return a tuple containing
        the data type and a function to unpack it.
        The type can be None for immutable types, instances,
        reference and dereferences.'''


    ### Private Methods ###

    def _continue_restoring_instance(self, instance, data):
        snapshot = self.unpack_data(data)
        # Delay instance initialization to the end to be sure
        # all snapshots circular references have been resolved
        self._instances.append((instance, snapshot))
        return instance


### Module Private ###

_global_registry = Registry()
