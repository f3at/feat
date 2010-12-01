import types

from zope.interface import implements, classProvides

from feat.interface.serialization import *

from . import decorator, adapter

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


@decorator.simple_class
def register(restorator):
    global _global_registry
    _global_registry.register(restorator)
    return restorator


@adapter.register(object, ISnapshotable)
class SnapshotableWrapper(object):
    '''Make any object a L{ISnapshotable} that return themselves.'''

    implements(ISnapshotable)

    def __init__(self, value):
        self.value = value

    ### ISnapshotable Methods ###

    def snapshot(self):
        return self.value


class MetaSerializable(type):

    def __init__(cls, name, bases, dct):
        if "type_name" not in dct:
            type_name = dct["__module__"] + "." + name
            setattr(cls, "type_name", type_name)
        super(MetaSerializable, cls).__init__(name, bases, dct)


class Snapshotable(object):
    __metaclass__ = MetaSerializable

    implements(ISnapshotable)

    ### ISnapshotable Methods ###

    def snapshot(self):
        return self.__dict__


class Serializable(Snapshotable):
    __metaclass__ = MetaSerializable

    classProvides(IRestorator)
    implements(ISerializable)

    type_name = None

    @classmethod
    def restore(cls, snapshot):
        obj = cls.__new__(cls)
        obj.recover(snapshot)
        return obj

    def recover(self, snapshot):
        self.__dict__.update(snapshot)


class Registry(object):

    implements(IRegistry)

    def __init__(self):
        self._registry = {} # {TYPE_NAME: IRestorator}


    ### IRegistry Methods ###

    def register(self, restorator):
        r = IRestorator(restorator)
        self._registry[r.type_name] = r


class Instance(object):

    implements(IInstance)

    __slots__ = ("type_name", "snapshot")

    def __init__(self, type_name, snapshot):
        self.type_name = type_name
        self.snapshot = snapshot

    def __repr__(self):
        return "<Instance %s: %r>" % (self.type_name, self.snapshot)


class Reference(object):

    implements(IReference)

    __slots__ = ("refid", "value")

    def __init__(self, refid, value):
        self.refid = refid
        self.value = value

    def __repr__(self):
        return "<Reference %s: %r>" % (self.refid, self.value)


class Dereference(object):

    implements(IDereference)

    __slots__ = ("refid", )

    def __init__(self, refid):
        self.refid = refid

    def __repr__(self):
        return "<Dereference %s>" % self.refid


class BaseSerializer(object):
    '''Base class for serializers handling references.'''

    implements(ISerializer)

    def __init__(self, formater=None):
        self._formater = formater and IFormater(formater)

        #FIXME: Add datetime types datetime, date, time and timedelta
        self._lookup = {tuple: self.pack_tuple,
                        list: self.pack_list,
                        set: self.pack_set,
                        dict: self.pack_dict,
                        str: self.pack_str,
                        unicode: self.pack_unicode,
                        int: self.pack_int,
                        long: self.pack_long,
                        float: self.pack_float,
                        bool: self.pack_bool,
                        type(None): self.pack_none}

        self.reset()

    ### Public Methods ###

    def reset(self):
        self._preserved = {}

    ### ISerializer Methods ###

    def serialize(self, obj):
        try:
            packed = self.pack_value(obj)
            if self._formater:
                return self._formater.format(packed)
            return packed
        finally:
            self.reset()

    ### Protected Methods, Used by sub-classes ###

    def pack_value(self, value):
        return self._lookup.get(type(value), self.pack_unknown)(value)

    def pack_unknown(self, value):
        # Checks if value support the serialization protocol
        if ISerializable.providedBy(value):
            return self.pack_serializable(ISerializable(value))

        # Now check if value is a base types sub-classes
        for otype, function in self._lookup.items():
            if isinstance(value, otype):
                return function(value)

        raise TypeError("Type %s not suported by serializer"
                        % type(value).__name__)

    def pack_identity(self, value):
        return value

    def pack_not_implemented(self, value):
        raise NotImplementedError()

    pack_str = pack_identity
    pack_int = pack_identity
    pack_long = pack_identity
    pack_float = pack_identity
    pack_none = pack_identity
    pack_bool = pack_identity
    pack_unicode = pack_identity

    pack_tuple = pack_not_implemented
    pack_list = pack_not_implemented
    pack_set = pack_not_implemented
    pack_dict = pack_not_implemented
    pack_serialized = pack_not_implemented

    ### Private Methods ###


class TreeSerializer(BaseSerializer):
    '''Serialize any python structure to a tree of basic python types,
    L{IInstance} and L{IReference}.

    Object have to implemente L{ISerializable} to be serialized.

    Examples::

        >> a = [1, 2, 3]
        >> b = [4, 5, 6]
        >> c = ['X', a, 'Y', b, 'Z', a]
        >> print TreeSerializer().serialize(c)
        ['X', <Reference 1: [1, 2, 3]>, 'Y', [4, 5, 6], 'Z', <Derefence: 1>]

        >> o = Serializable()
        >> o.foo = 42
        >> print TreeSerializer().serialize(o)
        <Instance feat.common.serialization.Serializable: {"foo": 42}>

    '''

    implements(ISerializer)

    def pack_tuple(self, value):
        return tuple([self.pack_value(v) for v in value])

    def pack_list(self, value):
        return [self.pack_value(v) for v in value]

    def pack_set(self, value):
        return set([self.pack_value(v) for v in value])

    def pack_dict(self, value):
        return dict([(self.pack_value(k), self.pack_value(v))
                     for k, v in value.iteritems()])

    def pack_serializable(self, value):
        return Instance(value.type_name, self.pack_value(value.snapshot()))


class SExpSerializer(BaseSerializer):
    '''Serialize any python structure into s expression compatible
    with twisted.spread.jelly.'''

    def pack_unicode(self, value):
        return [UNICODE_ATOM, value.encode(UNICODE_FORMAT_ATOM)]

    def pack_bool(self, value):
        return [BOOL_ATOM, BOOL_TRUE_ATOM if value else BOOL_FALSE_ATOM]

    def pack_none(self, value):
        return [NONE_ATOM]

    def pack_tuple(self, value):
        return [TUPLE_ATOM] + [self.pack_value(v) for v in value]

    def pack_list(self, value):
        return [LIST_ATOM] + [self.pack_value(v) for v in value]

    def pack_dict(self, value):
        return [DICT_ATOM] + [[self.pack_value(k), self.pack_value(v)]
                              for k, v in value.iteritems()]

    def pack_set(self, value):
        return [SET_ATOM] + [self.pack_value(v) for v in value]

    def pack_serializable(self, value):
        return [value.type_name, self.pack_value(value.snapshot())]


class Unserializer(object):

    implements(IUnserializer)

    def __init__(self, parser, registry=None):
        global _global_registry
        self._parser = IParser(parser)
        if registry:
            self._registry = IRegistry(registry)
        else:
            self._registry = _global_registry

    ### IUnserializer Methods ###

    def unserialize(self, data):
        pass


### Module Private ###

_global_registry = Registry()
