# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.spread import pb, jelly

from feat.common import decorator
from feat.agents.base import document


@decorator.parametrized_class
def register(klass, name):
    klass.type_name = name
    klass.document_type = name
    return document.register(klass)


def lookup(name):
    return document.lookup(name)


@document.register
class Descriptor(document.Document, pb.Copyable):

    document_type = 'descriptor'
    # Shard identifier (unicode)
    document.field('shard', None)
    # List of allocations
    document.field('allocations', dict())
    # List of partners
    document.field('partners', list())
    # The counter incremented at the agents startup
    document.field('instance_id', 0)


jelly.globalSecurity.allowInstancesOf(Descriptor)
