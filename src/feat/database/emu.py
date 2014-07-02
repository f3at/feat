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

from zope.interface import implements

from feat.common import log, defer
from feat.database.client import Connection, ChangeListener
from feat.agencies import common

from feat.database.interface import IDbConnectionFactory, IDatabaseDriver
from feat.database.interface import ConflictError, NotFoundError
from feat.database.interface import IViewFactory, IAttachmentPrivate


class Biggest(object):

    def __cmp__(self, other):
        return 1

BIGGEST = Biggest()


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
        # id -> name -> body
        self._attachments = {}
        # id -> view_name -> (key, value)
        self._view_cache = {}

        self._on_connected()

        # type_name -> int, used for generating nice agent IDs in
        # simulations
        self._doc_type_counters = dict()

        # list of all old revisions
        self._changes = list()

    ### IDbConnectionFactory

    def get_connection(self):
        return Connection(self)

    ### IDatabaseDriver

    def create_db(self):
        raise NotImplementedError("Not implemented in emu")

    def delete_db(self):
        raise NotImplementedError("Not implemented in emu")

    def replicate(self, source, target, **options):
        raise NotImplementedError("Not implemented in emu")

    def save_doc(self, doc, doc_id=None, following_attachments=None):
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
            if doc['_id'] not in self._attachments:
                self._attachments[doc['_id']] = dict()
            attachments = doc.get('_attachments', dict())
            for name in attachments:
                if attachments[name].get('follows'):
                    if name not in following_attachments:
                        raise ValueError("Document id %s had attachment name"
                                         " %s marked with follows=True, but"
                                         " it was not passed to save_doc() "
                                         % (doc['_id'], name))

                    del attachments[name]['follows']
                    attachments[name]['stub'] = True
                    b = following_attachments[name].get_body()
                    self._attachments[doc['_id']][name] = b

                elif name not in self._attachments[doc['_id']]:
                    raise ValueError("Document id %s body has attachment "
                                     "named %s "
                                     "but it is not in our cache " %
                                     (doc['_id'], name))
            for name in self._attachments[doc['_id']].keys():
                if name not in attachments:
                    del self._attachments[doc['_id']][name]
                    self.log('Deleted attachment %s of the doc: %s because '
                             'its not in the _attachments key' %
                             (name, doc['_id']))

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

    def copy_doc(self, doc_id, destination_id, rev=None):
        d = self.open_doc(doc_id)
        d.addCallback(defer.keep_param, defer.call_param,
                      'update', {'_id': destination_id, '_rev': rev})
        d.addCallback(json.dumps)
        d.addCallback(self.save_doc)
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
            doc['_deleted'] = True
            self._expire_cache(doc['_id'])
            for key in doc.keys():
                if key in ['_rev', '_deleted', '_id']:
                    continue
                del(doc[key])
            self.log('Marking document %r as deleted', doc_id)
            del self._attachments[doc['_id']]
            self._update_rev(doc)
            self._analize_changes(doc)
            d.callback(Response(ok=True, id=doc_id, rev=doc['_rev']))
        except (ConflictError, NotFoundError, ) as e:
            d.errback(e)

        return d

    def query_view(self, factory, **options):
        factory = IViewFactory(factory)
        use_reduce = factory.use_reduce and options.get('reduce', True)
        group = options.pop('group', False)
        group_level = options.pop('group_level', None)
        include_docs = options.pop('include_docs', False)
        if 'keys' in options and group_level:
            raise ValueError("CouchDB doesn't support the combination of using"
                             " 'group_level' and passing multiple keys.")

        if use_reduce and include_docs:
            raise ValueError("Query parameter 'include_docs' is invalid for "
                             "reduce views.")

        iterator = (self._perform_map(doc, factory)
                    for doc in self._iterdocs())
        # In erlang ordering of objects is different than in python.
        # Empty dict ({}) is the "biggest" value, by convetion its used
        # to denote the end of the range. In python {} < str, so we substitute
        # {} with a special object which always compares to bigger value
        for keyname in ('startkey', 'endkey'):
            if keyname in options and isinstance(options[keyname], tuple):
                options[keyname] = tuple(x if x != {} else BIGGEST
                                         for x in options[keyname])
        d = defer.succeed(iterator)
        d.addCallback(self._flatten, **options)
        if use_reduce:
            d.addCallback(self._perform_reduce, factory, group=group,
                          group_level=group_level)
        if include_docs:
            d.addCallback(self._include_docs)
        d.addCallback(self._apply_slice, **options)
        d.addCallback(self._sort_by_key, **options)
        if 'post_process' in options:
            tag = 'query to %s' % (factory.name, )
            if callable(options['post_process']):
                d.addCallback(options['post_process'], tag)
            else:
                d.addCallback(options['post_process'][0], tag,
                              *options['post_process'][1:])
        return d

    def disconnect(self):
        pass

    def save_attachment(self, doc_id, revision, attachment):
        attachment = IAttachmentPrivate(attachment)
        doc = self._documents.get(doc_id)
        if not doc:
            return defer.fail(NotFoundError(doc_id))
        if '_attachments' not in doc:
            doc['_attachments'] = dict()
        doc['_attachments'][attachment.name] = dict(
            stub=True,
            content_type=attachment.content_type,
            length=attachment.length)
        self._attachments[doc['_id']][attachment.name] = attachment.get_body()
        self._set_id_and_revision(doc, doc_id)
        r = Response(ok=True, id=doc['_id'], rev=doc['_rev'])
        return defer.succeed(r)

    def get_attachment(self, doc_id, name):
        if doc_id not in self._attachments:
            return defer.fail(NotFoundError(doc_id))
        if name not in self._attachments[doc_id]:
            return defer.fail(NotFoundError('%s/%s' % (doc_id, name)))
        return defer.succeed(self._attachments[doc_id][name])

    def get_update_seq(self):
        return defer.succeed(len(self._changes))

    def get_changes(self, filter_, limit=None, since=0):
        results = list()
        for seq in range(since, len(self._changes)):
            doc = self._changes[seq]
            if filter_ and not filter_.match(doc):
                continue
            results.append(
                dict(seq=seq, id=doc['_id'], changes=[{'rev': doc['_rev']}]))
        result = dict(results=results, last_seq=len(self._changes))
        return defer.succeed(result)

    def bulk_get(self, doc_ids):
        result = list()
        for doc_id in doc_ids:
            self.increase_stat('open_doc')
            try:
                doc = self._get_doc(doc_id)
                doc = copy.deepcopy(doc)
                value = dict(rev=doc['_rev'])
                if doc.get('_deleted', None):
                    value['deleted'] = True
                result.append({'_id': doc['_id'], 'value': value, 'doc': doc})
            except NotFoundError:
                result.append(dict(error="not_found"))
        return defer.succeed(dict(rows=result))

    ### public used in tests ###

    def load_fixture(self, body, attachment_bodies={}):
        '''
        Loads the document into the database from json string. Fakes the
        attachments if necessary.'''
        doc = json.loads(body)
        self._documents[doc['_id']] = doc
        self._attachments[doc['_id']] = dict()
        for name in doc.get('_attachments', list()):
            attachment_body = attachment_bodies.get(name, 'stub')
            self._attachments[doc['_id']][name] = attachment_body

    ### private ###

    def _include_docs(self, rows):
        '''rows here are tuples (key, value, id), returns a list of tuples
        (key, value, id, doc)'''
        resp = list()
        for row in rows:
            if isinstance(row[1], dict) and '_id' in row[1]:
                d_id = row[1]['_id']
            else:
                d_id = row[2]
            try:
                doc = self._get_doc(d_id)
                doc = copy.deepcopy(doc)
                if doc.get('_deleted', None):
                    raise NotFoundError('%s deleted' % d_id)
            except NotFoundError:
                # FIXME: this just returns None instead of dict if the
                # document is not there/was deleted.
                # I'm not sure if this is how couchdb would behave
                # check it!
                doc = None
            resp.append(row + (doc, ))
        return resp

    def _apply_slice(self, rows, **slice_options):
        skip = slice_options.get('skip', 0)
        limit = slice_options.get('limit', None)

        if skip > 0 or limit is not None:
            if limit is None:
                index = slice(skip, -1)
            else:
                index = slice(skip, skip + limit)
            rows = rows[index]

        return rows

    def _sort_by_key(self, rows, **options):
        descend = options.get('descending', False)
        return sorted(rows, key=operator.itemgetter(0), reverse=descend)

    def _matches_filter(self, tup, **filter_options):
        if 'key' in filter_options:
            if filter_options['key'] != tup[0]:
                return False
        if 'keys' in filter_options:
            if tup[0] not in filter_options['keys']:
                return False
        descending = filter_options.get('descending', False)
        if 'startkey' in filter_options:
            if ((not descending and filter_options['startkey'] > tup[0]) or
                (descending and filter_options['startkey'] < tup[0])):
                return False
        if 'endkey' in filter_options:
            if ((not descending and filter_options['endkey'] < tup[0]) or
                (descending and filter_options['endkey'] > tup[0])):
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
        res = list(x + (doc['_id'], ) for x in factory.perform_map(doc))
        self._set_cache(doc['_id'], factory.name, res)
        return res

    def _perform_reduce(self, map_results, factory, group=False,
                        group_level=None):
        '''
        map_results here is a list of tuples (key, value, id)
        '''

        def get_group_key(key, group, group_level):
            if group:
                return key
            return key[0:group_level]

        if not group and group_level is None:
            keys = map(operator.itemgetter(0), map_results)
            values = map(operator.itemgetter(1), map_results)
            return self._reduce_values(factory, None, keys, values)
        else:
            groups = dict()
            for row in map_results:
                key, value = row[:2]
                group_key = get_group_key(key, group, group_level)
                if group_key not in groups:
                    groups[group_key] = list()
                groups[group_key].append((key, value))
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
        if not factory.reduce:
            pass
        elif factory.reduce == '_sum':
            result = sum(values)
        elif factory.reduce == '_count':
            result = len(values)
        else:
            result = factory.perform_reduce(keys, values)

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

        doc['_id'] = doc_id
        self._update_rev(doc)

        return doc

    def _get_doc(self, docId):
        doc = self._documents.get(docId, None)
        if not doc:
            raise NotFoundError("%s missing" % (docId, ))
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

    def _update_rev(self, doc):
        cur_rev = doc.get('_rev', None)
        if not cur_rev:
            counter = 1
        else:
            counter, _ = cur_rev.split('-')
            counter = int(counter) + 1
        rand = unicode(uuid.uuid1()).replace('-', '')
        doc['_rev'] = unicode("%d-%s" % (counter, rand))
        self._changes.append(copy.deepcopy(doc))


class Response(dict):

    pass
