import types

from zope.interface import implements, classProvides

from feat.interface.serialization import *

from . import decorator, adapter


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


### Module Private ###

_global_registry = Registry()
