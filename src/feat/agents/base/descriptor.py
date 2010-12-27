# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from feat.common import serialization
from . import document


@serialization.register
@document.register
class Descriptor(document.Document):

    document_type = 'descriptor'

    def __init__(self, shard=None, **kwargs):
        document.Document.__init__(self, **kwargs)
        self.shard = shard

    def get_content(self):
        return dict(shard=self.shard)
