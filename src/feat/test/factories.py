import inspect
import sys


def build(doc_class, **options):
    '''Builds document of selected class with default parameters for testing'''

    name = "%s_factory" % doc_class.__name__.lower()
    module = sys.modules[__name__]
    members = inspect.getmembers(module, lambda x: inspect.isfunction(x) and\
                                 x.__name__ == name)
    if len(members) != 1:
        raise AttributeError("Couldn't locate faker for document class: %r"\
                                % doc_class.__name__)
    _, factory = members[0]
    return doc_class(**factory(**options))


def descriptor_factory(**options):
    options['shard'] = options.get('shard', 'lobby')
    return options
