# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4


class Document(object):

    def __init__(self, uuid, rev=None):
        self._id = uuid
        self._rev = rev

    def to_json(self):
        pass
