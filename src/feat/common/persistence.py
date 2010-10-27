
from zope.interface import implements

from feat.interface import serialization


def register(restorator):
    global _global_registry
    return _global_registry.register(restorator)


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
