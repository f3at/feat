
from zope.interface import implements, classProvides

from feat.interface.serialization import *

from . import decorator, adapter


@decorator.simple_class
def register(restorator):
    global _global_registry
    _global_registry.register(restorator)
    return restorator


@adapter.register(object, ISnapshot)
class SnapshotWrapper(object):
    '''Make any object a L{ISnapshot} that return themselves.'''

    implements(ISnapshot)

    def __init__(self, value):
        self.value = value

    ### ISnapshot Methods ###

    def snapshot(self):
        return self.value


class MetaSerializable(type):

    def __init__(cls, name, bases, dct):
        if "type_name" not in dct:
            type_name = dct["__module__"] + "." + name
            setattr(cls, "type_name", type_name)
        super(MetaSerializable, cls).__init__(name, bases, dct)


class Snapshot(object):
    __metaclass__ = MetaSerializable

    implements(ISnapshot)

    ### ISnapshot Methods ###

    def snapshot(self):
        return self.__dict__


class Serializable(Snapshot):
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


class Serializer(object):

    implements(ISerializer)

    def __init__(self, formater):
        self._formater = IFormater(formater)

    ### ISerializer Methods ###

    def serialize(self, obj):
        pass


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
