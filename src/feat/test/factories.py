import inspect
import sys
import re

from feat.agents.base import document


def build(document_type, **options):
    '''Builds document of selected class with default parameters for testing'''

    try:
        doc_class = document.documents[document_type]
    except KeyError:
        raise AttributeError("Unknown document type: %r", document_type)

    name = "%s_factory" % re.sub(r'-', '_', document_type.lower())
    module = sys.modules[__name__]
    members = inspect.getmembers(module, lambda x: inspect.isfunction(x) and\
                                 x.__name__ == name)
    if len(members) != 1:
        raise AttributeError("Couldn't locate faker for document type: %r"\
                                % document_type)
    _, factory = members[0]
    return doc_class(**factory(**options))


def descriptor_factory(**options):
    options['shard'] = options.get('shard', u'lobby')
    return options


def shard_agent_factory(**options):
    options = descriptor_factory(**options)
    return options


def host_agent_factory(**options):
    options = descriptor_factory(**options)
    return options


def base_agent_factory(**options):
    options = descriptor_factory(**options)
    return options
