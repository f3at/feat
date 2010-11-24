# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

documents = dict()


def register(klass):
    global documents
    documents[klass.document_type] = klass
    return klass


class Document(object):

    def __init__(self, _id=None, _rev=None, **kwargs):
        self._decode(_id)
        self._decode(_rev)

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
        doc_id = self._decode(response.get('id', None))
        rev = self._decode(response.get('rev', None))
        if doc_id:
            self._doc_id = doc_id
        if rev:
            self._rev = rev

        return self

    def _decode(self, var):
        '''
        Decodes unicode to string if necessary. This is important for some
        fields, escescially doc_id which is used by CouchDB to generate URLs
        '''

        if isinstance(var, unicode):
            return var.encode('utf-8')
        else:
            return var
