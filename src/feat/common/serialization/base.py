import copy

from zope.interface import implements

from feat.common import decorator, adapter
from feat.interface.serialization import *


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
    '''Simple L{ISnapshotable} that snapshot the full instance dictionary.
    If the class attribute type_name is not defined, the canonical
    name of the class is used.'''

    __metaclass__ = MetaSnapshotable

    implements(ISnapshotable)

    ### ISnapshotable Methods ###

    def snapshot(self):
        return self.__dict__


class MetaSerializable(MetaSnapshotable):

    implements(IRestorator)


class Serializable(Snapshotable):
    '''Simple L{ISerializable} that serialize and restore the full instance
    dictionary. If the class attribute type_name is not defined, the canonical
    name of the class is used.'''

    __metaclass__ = MetaSerializable

    #classProvides(IRestorator)
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
    declaration time, overriding any flatpassten_* method will not work.
    In case it would be needed in the future, the lookup table initialization
    should be moved to the constructor and self should not be passed anymore
    as the first parameter because the function would be then bound.

    #FIXME: Add datetime types datetime, date, time and timedelta

    '''

    implements(IFreezer, IConverter)

    pack_str = None
    pack_unicode = None
    pack_int = None
    pack_long = None
    pack_float = None
    pack_bool = None
    pack_none = None
    pack_tuple = None
    pack_list = None
    pack_item = None
    pack_dict = None
    pack_type = None
    pack_instance = None
    pack_reference = None
    pack_dereference = None
    pack_frozen_instance = None

    def __init__(self, post_converter=None):
        self._post_converter = post_converter and IConverter(post_converter)
        self._reset()

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

    ### Private Methods ###

    def _reset(self):
        self._freezing = False # If we are freezing or serializing
        self._preserved = {} # {OBJ_ID: FLATTENED_STRUCTURE}
        self._refids = {} # {OBJ_ID: REFERENCE_ID}
        self._references = {} # {OBJ_ID: REFERENCE_CONTAINER}
        self._refid = 0

    def _convert(self, data):
        try:
            # Flatten the value to the list-only format with packer function
            flattened = self.flatten_value(data)
            # Pack all the value with there own packer functions
            packed = self._pack_value(flattened)
            # Post-convert the data if a convert was specified
            return self._post_convertion(packed)
        finally:
            # Reset the state to cleanup all references
            self._reset()

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
        # Retrieve the value container
        container = self._preserved[ident]
        # Set the value in place, even if it has been referenced
        container[:] = packer, data
        # If the value has been referenced, return the reference
        if ident in self._references:
            return self._references[ident]
        # Otherwise return the value itself
        return container

    def _pack_value(self, data):
        if not isinstance(data, (list, tuple)):
            return data
        packer, value = data
        if isinstance(value, list):
            value = [self._pack_value(d) for d in value]
        if packer is not None:
            return packer(value)
        return value

    def _post_convertion(self, data):
        if self._post_converter:
            return self._post_converter.convert(data)
        return data

    def flatten_value(self, value):
        vtype = type(value)
        default = Serializer.flatten_unknown
        return self._lookup.get(vtype, default)(self, value)

    def flatten_unknown(self, value):
        # Checks if value support the current required protocol
        # Could be ISnapshotable or ISerializable
        if self._freezing:
            if ISnapshotable.providedBy(value):
                return self.flatten_frozen_instance(ISnapshotable(value))
        else:
            if ISerializable.providedBy(value):
                return self.flatten_instance(ISerializable(value))

        raise TypeError("Type %s not supported by serializer %s"
                        % (type(value).__name__, type(self).__name__))

    def flatten_str(self, value):
        return self.pack_str, value

    def flatten_unicode(self, value):
        return self.pack_unicode, value

    def flatten_int(self, value):
        return self.pack_int, value

    def flatten_long(self, value):
        return self.pack_long, value

    def flatten_float(self, value):
        return self.pack_float, value

    def flatten_none(self, value):
        return self.pack_none, value

    def flatten_bool(self, value):
        return self.pack_bool, value

    def flatten_item(self, value):
        key, value = value
        return self.pack_item, [self.flatten_value(key),
                                self.flatten_value(value)]

    @referenceable
    def flatten_tuple(self, value):
        return self.pack_tuple, [self.flatten_value(v) for v in value]

    @referenceable
    def flatten_list(self, value):
        return self.pack_list, [self.flatten_value(v) for v in value]

    @referenceable
    def flatten_set(self, value):
        return self.pack_set, [self.flatten_value(v) for v in value]

    @referenceable
    def flatten_dict(self, value):
        return self.pack_dict, [self.flatten_item(i)
                                for i in value.iteritems()]

    @referenceable
    def flatten_frozen_instance(self, value):
        return self.pack_frozen_instance, self.flatten_value(value.snapshot())

    @referenceable
    def flatten_instance(self, value):
        return self.pack_instance, [[self.pack_type, value.type_name],
                                     self.flatten_value(value.snapshot())]

    ### Setup lookup table ###

    _lookup = {tuple: flatten_tuple,
               list: flatten_list,
               set: flatten_set,
               dict: flatten_dict,
               str: flatten_str,
               unicode: flatten_unicode,
               int: flatten_int,
               long: flatten_long,
               float: flatten_float,
               bool: flatten_bool,
               type(None): flatten_none}


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

    def __init__(self, pre_converter=None, registry=None):
        global _global_registry
        self._pre_converter = pre_converter and IConverter(pre_converter)
        self._registry = IRegistry(registry) if registry else _global_registry
        self._reset()

    ### IConverter Methods ###

    def convert(self, data):
        try:
            # Pre-convert the data if a convertor was specified
            converted = self._pre_convertion(data)
            # Unpack the first level of values
            unpacked = self.unpack_data(converted)
            # Continue unpacking level by level
            self._finish_unpacking()
            # Should be finished by now
            return unpacked
        finally:
            # Reset the state to cleanup all references
            self._reset()

    ### Protected Methods ###

    def delay_unpacking(self, container, fun, *args, **kwargs):
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

    def restore_instance(self, type_name, snapshot):
        # Lookup the registry for a IRestorator
        restorator = self._registry.lookup(type_name)
        # Prepare the instance for recovery
        instance = restorator.prepare()
        # Delay the instance restoration for later to handle circular refs
        return self.delay_unpacking(instance,
                                    self._continue_restoring_instance,
                                    instance, snapshot)

    def restore_reference(self, refid, data):
        if refid in self._references:
            raise ValueError("Multiple references found with "
                             "the same identifier: %s" % refid)
        value = self.unpack_data(data)
        self._references[refid] = value
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
        return self._references[refid]

    ### Virtual Methods, to be Overridden by Sub-Classes ###

    def unpack_data(self, data):
        '''Should be overridden by sub-classes.'''

    ### Private Methods ###

    def _reset(self):
        self._references = {} # {REFERENCE_ID: OBJECT}
        self._pending = [] # Pendings unpacking
        self._instances = [] # [(INSTANCE, SNAPSHOT)]
        self._delayed = 0 # If we are in a delayable unpacking

    def _pre_convertion(self, data):
        if self._pre_converter is not None:
            return self._pre_converter.convert(data)
        return data

    def _continue_restoring_instance(self, instance, data):
        snapshot = self.unpack_data(data)
        # Delay instance initialization to the end to be sure
        # all snapshots circular references have been resolved
        self._instances.append((instance, snapshot))
        return instance

    def _finish_unpacking(self):
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


### Module Private ###

_global_registry = Registry()
