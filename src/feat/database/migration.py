from zope.interface import implements

from feat.common import serialization, registry
from feat.database import common

from feat.database.interface import IMigration


class Migration(object):

    unserializer_factory = common.CouchdbUnserializer
    use_custom_registry = False

    implements(IMigration)
    source_ver = None
    target_ver = None
    type_name = None

    def __init__(self, source_ver=None, target_ver=None, type_name=None):
        if source_ver is not None:
            self.source_ver = source_ver
        if target_ver is not None:
            self.target_ver = target_ver
        if type_name is not None:
            self.type_name = type_name

        if self.source_ver is None:
            raise ValueError("You have to set source version")
        if self.target_ver is None:
            raise ValueError("You have to set target version")
        if self.type_name is None:
            raise ValueError("You have to set the type name")

        if self.use_custom_registry:
            self.registry = r = serialization.get_registry().clone()
            self.unserializer = type(self).unserializer_factory(registry=r)
        else:
            self.registry = serialization.get_registry()

    ### to be implemented in child classes ###

    def asynchronous_hook(self, connection, document, context):
        pass

    def synchronous_hook(self, snapshot):
        return snapshot


class Registry(registry.BaseRegistry):
    """Keep track of L{IRestorator}. Used by unserializers."""

    allow_blank_application = True
    verify_interface = IMigration
    allow_none_key = False

    def register(self, obj, key=None, application=None):
        if key is None:
            key = (obj.type_name, obj.source_ver, obj.target_ver)
        registry.BaseRegistry.register(self, obj, key, application)


_global_registry = Registry()


def get_registry():
    global _global_registry
    return _global_registry


def register(migration, application=None):
    global _global_registry
    return _global_registry.register(migration)
