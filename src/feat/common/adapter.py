from twisted.python import components

from feat.common import decorator


@decorator.parametrized_class
def register(cls, adapted, interface):
    components.registerAdapter(cls, adapted, interface)
    return cls
