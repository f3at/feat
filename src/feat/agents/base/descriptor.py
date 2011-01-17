# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from feat.common import serialization
from . import document


@document.register
class Descriptor(document.Document):

    document_type = 'descriptor'
    document.field('shard', None)
    # List of allocations
    document.field('allocations', list())
