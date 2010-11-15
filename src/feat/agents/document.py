# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import json


class Document(object):

    fields = ['_id', '_rev']

    def __init__(self, **kwargs):
        self._fields = []
        for cls in self.__class__.__mro__:
            if issubclass(cls, Document):
                self._fields += cls.fields

        for field in self._fields:
            self.__setattr__(field, None)

        for key in kwargs:
            if key in self._fields:
                self.__setattr__(key, kwargs[key])
            else:
                raise AttributeError('Only fields specified in class '
                                     'definition are allowed in __init__')

    def to_json(self):
        resp = dict()
        for key in self._fields:
            resp[key] = self.__dict__[key]

        return json.dumps(resp)
