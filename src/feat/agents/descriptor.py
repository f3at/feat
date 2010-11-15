# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import uuid

from . import document


class Descriptor(document.Document):

    fields = ['shard']

    def __init__(self, **kwargs):
        kwargs['shard'] = kwargs.get('shard', 'lobby')
        kwargs['_id'] = kwargs.get('_id', str(uuid.uuid1()))
        document.Document.__init__(self, **kwargs)
