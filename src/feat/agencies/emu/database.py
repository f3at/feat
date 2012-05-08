# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import copy
import uuid
import json
import operator

from twisted.internet import defer
from zope.interface import implements

from feat.common import log
from feat.agencies.database import Connection, ChangeListener
from feat.agencies import common

from feat.agencies.interface import IDbConnectionFactory, IDatabaseDriver
from feat.agencies.interface import ConflictError, NotFoundError
from feat.interface.view import IViewFactory


class Database(common.ConnectionManager, log.LogProxy, ChangeListener,
               common.Statistics):

    implements(IDbConnectionFactory, IDatabaseDriver)

    '''
    Imitates the CouchDB server internals.
    '''

    log_category = "emu-database"

    def __init__(self):
        common.ConnectionManager.__init__(self)
        log.LogProxy.__init__(self, log.get_default() or log.FluLogKeeper())
        ChangeListener.__init__(self, self)
        common.Statistics.__init__(self)

        # id -> document
        self._documents = {}
        # id -> view_name -> (key, value)
        self._view_cache = {}

        self._on_connected()

        # type_name -> int, used for generating nice agent IDs in
        # simulations
        self._doc_type_counters = dict()

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
            self._analize_changes(doc)
            d.callback(r)
        except (ConflictError, ValueError, ) as e:
            d.errback(e)

        return d

    def _analize_changes(self, doc):
        for filter_i in self._filters.itervalues():
            if filter_i.match(doc):
                deleted = doc.get('_deleted', False)
                filter_i.notified(doc['_id'], doc['_rev'], deleted)

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
                raise NotFoundError('%s deleted' % doc_id)
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
                raise NotFoundError('%s deleted' % doc_id)
            doc['_rev'] = self._generate_rev(doc)
            doc['_deleted'] = True
            self._expire_cache(doc['_id'])
            for key in doc.keys():
                if key in ['_rev', '_deleted', '_id']:
                    continue
                del(doc[key])
            self.log('Marking document %r as deleted', doc_id)
            self._analize_changes(doc)
            d.callback(Response(ok=True, id=doc_id, rev=doc['_rev']))
        except (ConflictError, NotFoundError, ) as e:
            d.errback(e)

        return d

    def query_view(self, factory, **options):
        factory = IViewFactory(factory)
        use_reduce = factory.use_reduce and options.get('reduce', True)
        group = options.pop('group', False)
        iterator = (self._perform_map(doc, factory)
                    for doc in self._iterdocs())
        d = defer.succeed(iterator)
        d.addCallback(self._flatten, **options)
        if use_reduce:
            d.addCallback(self._perform_reduce, factory, group=group)
        d.addCallback(self._apply_slice, **options)
        return d

    def disconnect(self):
        pass

    ### private

    def _apply_slice(self, rows, **slice_options):
        skip = slice_options.get('skip', 0)
        limit = slice_options.get('limit', None)
        descend = slice_options.get('descending', False)

        if skip > 0 or limit is not None:
            if limit is None:
                index = slice(skip, -1)
            else:
                index = slice(skip, skip + limit)
            rows = rows[index]

        if descend:
            rows.reverse()

        return rows

    def _matches_filter(self, tup, **filter_options):
        if 'key' in filter_options:
            if filter_options['key'] != tup[0]:
                return False
        if 'startkey' in filter_options:
            if filter_options['startkey'] > tup[0]:
                return False
        if 'endkey' in filter_options:
            if filter_options['endkey'] < tup[0]:
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

    def _perform_reduce(self, map_results, factory, group=False):
        '''
        map_results here is a list of tuples (key, value)
        '''
        if not group:
            keys = map(operator.itemgetter(0), map_results)
            values = map(operator.itemgetter(1), map_results)
            return self._reduce_values(factory, None, keys, values)
        else:
            groups = dict()
            for key, value in map_results:
                if key not in groups:
                    groups[key] = list()
                groups[key].append((key, value))
            resp = list()
            for group_key, results in groups.iteritems():
                keys = map(operator.itemgetter(0), results)
                values = map(operator.itemgetter(1), results)
                resp.extend(
                    self._reduce_values(factory, group_key, keys, values))
            return resp

    def _reduce_values(self, factory, group_key, keys, values):
        if not values:
            return []
        if callable(factory.reduce):
            result = factory.reduce(keys, values)
        elif factory.reduce == '_sum':
            result = sum(values)
        elif factory.reduce == '_count':
            result = len(values)

        return [(group_key, result, )]

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
            doc_id = self._generate_id(doc)
            self.log("Generating new id for the document: %r", doc_id)
        else:
            old_doc = self._documents.get(doc_id, None)
            if old_doc:
                self.log('Checking the old document revision')
                if not old_doc.get('_deleted', False):
                    if (doc.get('_rev', None) is None
                        or old_doc['_rev'] != doc['_rev']):
                        raise ConflictError('Document update conflict.')

        doc['_rev'] = self._generate_rev(doc)
        doc['_id'] = doc_id

        return doc

    def _get_doc(self, docId):
        doc = self._documents.get(docId, None)
        if not doc:
            raise NotFoundError("%s missing" % docId)
        return doc

    def _generate_id(self, doc):
        doc_type = doc.get('.type', None)
        if doc_type:
            if doc_type not in self._doc_type_counters:
                self._doc_type_counters[doc_type] = 0
            self._doc_type_counters[doc_type] += 1
            return unicode("%s_%d" % (doc_type,
                                      self._doc_type_counters[doc_type]))
        else:
            return unicode(uuid.uuid1())

    def _generate_rev(self, doc):
        cur_rev = doc.get('_rev', None)
        if not cur_rev:
            counter = 1
        else:
            counter, _ = cur_rev.split('-')
            counter = int(counter) + 1
        rand = unicode(uuid.uuid1()).replace('-', '')
        return unicode("%d-%s" % (counter, rand))


class Response(dict):

    pass
