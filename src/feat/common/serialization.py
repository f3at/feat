
from zope.interface import implements, classProvides

from feat.interface import serialization


def register(restorator):
    global _global_registry
    return _global_registry.register(restorator)


class MetaSerializable(type):

    def __init__(cls, name, bases, dct):
        if "type_name" not in dct:
            type_name = dct["__module__"] + "." + name
            setattr(cls, "type_name", type_name)
        super(MetaSerializable, cls).__init__(name, bases, dct)


class Snapshot(object):
    __metaclass__ = MetaSerializable

    implements(serialization.ISnapshot)

    def snapshot(self, context={}):
        return self.__dict__


class Serializable(Snapshot):
    __metaclass__ = MetaSerializable

    classProvides(serialization.IRestorator)
    implements(serialization.ISerializable)

    type_name = None

    @classmethod
    def restore(cls, snapshot, context={}):
        obj = cls.__new__(cls)
        obj.recover(snapshot, context)
        return obj

    def recover(self, snapshot, context={}):
        self.__dict__.update(snapshot)


class Registry(object):

    implements(serialization.IRegistry)

    def __init__(self):
        self._registry = {} # {TYPE_NAME: IRestorator}


    ### IRegistry Methods ###

    def register(self, restorator):
        r = serialization.IRestorator(restorator)
        self._registry[r.type_name] = r


class Serializer(object):

    implements(serialization.ISerializer)

    def __init__(self, formater):
        self._formater = serialization.IFormater(formater)

    ### ISerializer Methods ###

    def serialize(self, obj):
        pass


class Unserializer(object):

    implements(serialization.IUnserializer)

    def __init__(self, parser, registry=None):
        global _global_registry
        self._parser = serialization.IParser(parser)
        if registry:
            self._registry = serialization.IRegistry(registry)
        else:
            self._registry = _global_registry

    ### IUnserializer Methods ###

    def unserialize(self, data):
        pass


### Module Private ###

_global_registry = Registry()
