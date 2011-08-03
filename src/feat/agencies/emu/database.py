# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import copy
import uuid
import json
import operator

from twisted.internet import defer, reactor
from zope.interface import implements

from feat.common import log
from feat.agencies.database import Connection, ChangeListener
from feat.agencies import common

from feat.agencies.interface import *
from feat.interface.view import *


class Database(common.ConnectionManager, log.LogProxy, ChangeListener,
               common.Statistics):

    implements(IDbConnectionFactory, IDatabaseDriver)

    '''
    Imitates the CouchDB server internals.
    '''

    log_category = "emu-database"

    def __init__(self):
        common.ConnectionManager.__init__(self)
        log.LogProxy.__init__(self, log.FluLogKeeper())
        ChangeListener.__init__(self, self)
        common.Statistics.__init__(self)

        # id -> document
        self._documents = {}
        # id -> view_name -> (key, value)
        self._view_cache = {}

        self._on_connected()

    ### IDbConnectionFactory

    def get_connection(self):
        return Connection(self)

    ### IDatabaseDriver

    def save_doc(self, doc, doc_id=None):
        '''Imitate sending HTTP request to CouchDB server'''

        self.log("save_document called for doc: %r", doc)

        d = defer.Deferred()

        try:
            if not isinstance(doc, (str, unicode, )):
                raise ValueError('Doc should be either str or unicode')
            doc = json.loads(doc)
            doc = self._set_id_and_revision(doc, doc_id)

            self.increase_stat('save_doc')

            self._documents[doc['_id']] = doc
            self._expire_cache(doc['_id'])

            r = Response(ok=True, id=doc['_id'], rev=doc['_rev'])
            self._trigger_change(doc['_id'], doc['_rev'])
            d.callback(r)
        except (ConflictError, ValueError, ) as e:
            d.errback(e)

        return d

    def open_doc(self, doc_id):
        '''Imitated fetching the document from the database.
        Doesnt implement options from paisley to get the old revision or
        get the list of revision.
        '''
        d = defer.Deferred()
        self.increase_stat('open_doc')
        try:
            doc = self._get_doc(doc_id)
            doc = copy.deepcopy(doc)
            if doc.get('_deleted', None):
                raise NotFoundError('deleted')
            d.callback(Response(doc))
        except NotFoundError as e:
            d.errback(e)

        return d

    def delete_doc(self, doc_id, revision):
        '''Imitates sending DELETE request to CouchDB server'''
        d = defer.Deferred()

        self.increase_stat('delete_doc')

        try:
            doc = self._get_doc(doc_id)
            if doc['_rev'] != revision:
                raise ConflictError("Document update conflict.")
            if doc.get('_deleted', None):
                raise NotFoundError('deleted')
            doc['_rev'] = self._generate_id()
            doc['_deleted'] = True
            self._expire_cache(doc['_id'])
            self.log('Marking document %r as deleted', doc_id)
            self._trigger_change(doc['_id'], doc['_rev'])
            d.callback(Response(ok=True, id=doc_id, rev=doc['_rev']))
        except (ConflictError, NotFoundError, ) as e:
            d.errback(e)

        return d

    def query_view(self, factory, **options):
        factory = IViewFactory(factory)
        use_reduce = factory.use_reduce and options.get('reduce', True)
        iterator = (self._perform_map(doc, factory)
                    for doc in self._iterdocs())
        d = defer.succeed(iterator)
        d.addCallback(self._flatten, **options)
        if use_reduce:
            d.addCallback(self._perform_reduce, factory)
        return d

    ### private

    def _matches_filter(self, tup, **filter_options):
        # We only support filtering by key at the moment
        if 'key' in filter_options:
            if filter_options['key'] != tup[0]:
                return False
        return True

    def _flatten(self, iterator, **filter_options):
        '''
        iterator here gives as lists of tuples. Method flattens the structure
        to a single list of tuples.
        '''
        resp = list()
        for entry in iterator:
            for tup in entry:
                if self._matches_filter(tup, **filter_options):
                    resp.append(tup)
        return resp

    def _perform_map(self, doc, factory):
        cached = self._get_cache(doc['_id'], factory.name)
        if cached:
            return cached
        res = list(factory.map(doc))
        self._set_cache(doc['_id'], factory.name, res)
        return res

    def _perform_reduce(self, map_results, factory):
        '''
        map_results here is a list of tuples (key, value)
        '''
        keys = map(operator.itemgetter(0), map_results)
        values = map(operator.itemgetter(1), map_results)
        if not values:
            return []
        if callable(factory.reduce):
            result = factory.reduce(keys, values)
        elif factory.reduce == '_sum':
            result = sum(values)
        elif factory.reduce == '_count':
            result = len(values)

        return [(None, result, )]

    def _iterdocs(self):
        for did, doc in self._documents.iteritems():
            if doc.get('_deleted', False):
                continue
            yield doc

    def _get_cache(self, doc_id, view_name):
        return self._view_cache.get(doc_id, {}).get(view_name, None)

    def _set_cache(self, doc_id, view_name, value):
        if doc_id not in self._view_cache:
            self._view_cache[doc_id] = dict()
        self._view_cache[doc_id][view_name] = value

    def _expire_cache(self, doc_id):
        self._view_cache.pop(doc_id, None)

    def _set_id_and_revision(self, doc, doc_id):
        doc_id = doc_id or doc.get('_id', None)
        if doc_id is None:
            doc_id = self._generate_id()
            self.log("Generating new id for the document: %r", doc_id)
        else:
            old_doc = self._documents.get(doc_id, None)
            if old_doc:
                self.log('Checking the old document revision')
                if doc.get('_rev', None) is None or\
                       old_doc['_rev'] != doc['_rev']:
                    raise ConflictError('Document update conflict.')

        doc['_rev'] = self._generate_id()
        doc['_id'] = doc_id

        return doc

    def _get_doc(self, docId):
        doc = self._documents.get(docId, None)
        if not doc:
            raise NotFoundError("missing")
        return doc

    def _generate_id(self):
        return unicode(uuid.uuid1())


class Response(dict):

    pass
