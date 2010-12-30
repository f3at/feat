# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from feat.common import serialization
from . import document


@document.register
class Descriptor(document.Document):

    document_type = 'descriptor'

    def __init__(self, **fields):
        document.Document.__init__(self, **fields)
        valid_fields = ('shard', )
        self._set_fields(valid_fields, fields)

    def snapshot(self):
        res = document.Document.snapshot(self)
        res['shard'] = self.shard
        return res

    def recover(self, snapshot):
        document.Document.recover(self, snapshot)
        self.shard = snapshot.get('shard', None)
