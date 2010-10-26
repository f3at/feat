# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4


class Document(object):

    def __init__(self, uuid, rev=None):
        self._uuid = uuid
        self._rev = rev

    @property
    def uuid(self):
        return self._uuid

    @property
    def rev(self):
        return self._rev