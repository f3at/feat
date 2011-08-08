from feat.common import decorator, serialization

registry = dict()


@decorator.parametrized_class
def register(klass, name, configuration_id=None):
    global registry
    registry[name] = klass
    doc_id = configuration_id or name + "_conf"
    klass.descriptor_type = name
    klass.type_name = name + ":data"
    klass.configuration_doc_id = doc_id
    serialization.register(klass)
    return klass


def registry_lookup(name):
    global registry
    return registry.get(name, None)
