# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from feat.common import serialization, decorator
from feat.agents.base import document


@decorator.parametrized_class
def register(klass, name):
    klass.type_name = name
    klass.document_type = name
    return document.register(klass)


@document.register
class Descriptor(document.Document):

    document_type = 'descriptor'
    # Shard identifier (unicode)
    document.field('shard', None)
    # List of allocations
    document.field('allocations', list())
    # List of partners
    document.field('partners', list())
