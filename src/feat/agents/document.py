# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

documents = dict()


def register(klass):
    global documents
    documents[klass.document_type] = klass
    return klass


class Document(object):

    def __init__(self, _id=None, _rev=None, **kwargs):
        if _id:
            self._type_check(_id, '_id', str)
        if _rev:
            self._type_check(_rev, '_rev', str)

        self._doc_id = _id
        self._rev = _rev

    @property
    def doc_id(self):
        return self._doc_id

    @property
    def rev(self):
        return self._rev

    def get_content(self):
        raise NotImplementedError("'get_content' method should be overloaded")

    def update(self, response):
        '''
        Updates id and rev basing on response from database.

        @param response: dict with keys id and rev
        @type response: dict
        @returns: updated document
        '''

        doc_id = response.get('id', None)
        rev = response.get('rev', None)
        if doc_id:
            self._type_check(doc_id, 'doc_id', str)
            self._doc_id = doc_id
        if rev:
            self._type_check(rev, 'rev', str)
            self._rev = rev

        return self

    def _type_check(self, to_check, var_name, type):
        if not isinstance(to_check, type):
            raise RuntimeError('%s should be of type %r, got %r instead' %
                               (var_name, type, to_check.__class__, ))
