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
import uuid
import urllib

from twisted.internet import reactor
from zope.interface import implements

from feat.common import log, defer, time
from feat.common.serialization import json
from feat.database import document, query

from feat.database.interface import IDatabaseClient, IDatabaseDriver
from feat.database.interface import IRevisionStore, IDocument, IViewFactory
from feat.database.interface import NotFoundError
from feat.interface.generic import ITimeProvider


class ViewFilter(object):

    def __init__(self, view, params):
        self.view = view
        self._request = dict(query=params)
        self.name = '?'.join([self.view.name, urllib.urlencode(params)])
        # listener_id -> callback
        self._listeners = dict()

    def match(self, doc):
        # used only by emu
        return self.view.filter(doc, self._request)

    def add_listener(self, callback, listener_id):
        self._listeners[listener_id] = callback

    def cancel_listener(self, listener_id):
        popped = self._listeners.pop(listener_id, None)
        return popped is not None

    def notified(self, doc_id, rev, deleted):
        for cb in self._listeners.itervalues():
            reactor.callLater(0, cb, doc_id, rev, deleted)

    def extract_params(self):
        if not self._listeners:
            # returning None prevents channel for being established
            return
        p = dict(self._request['query'])
        p['filter'] = "%s/%s" % (self.view.design_doc_id, self.view.name)
        return p


class DocIdFilter(object):

    def  __init__(self):
        self.name = 'doc_ids'
        # doc_ids -> [(callback, listener_id)]
        self._listeners = {}

    def match(self, doc):
        # used only by emu
        return doc['_id'] in self._listeners.keys()

    def notified(self, doc_id, rev, deleted):
        listeners = self._listeners.get(doc_id, list())
        for cb, _ in listeners:
            reactor.callLater(0, cb, doc_id, rev, deleted)

    def add_listener(self, callback, listener_id, doc_ids):
        for doc_id in doc_ids:
            cur = self._listeners.get(doc_id, list())
            cur.append((callback, listener_id, ))
            self._listeners[doc_id] = cur

    def cancel_listener(self, listener_id):
        changed = False
        for values in self._listeners.itervalues():
            iterator = (x for x in values if x[1] == listener_id)
            for matching in iterator:
                changed = True
                values.remove(matching)
        for key, values in self._listeners.items():
            # cleanup empty entry
            if not values:
                del(self._listeners[key])

        return changed

    def extract_params(self):
        if not self._listeners:
            # returning None prevents channel for being established
            return
        # FIXME: after upgrading couchdb to a version supporting builting
        # filter for doc_ids, pass here the correct params to trigger using it
        return dict()


class ChangeListener(log.Logger):
    '''
    Base class for .net.database.Database and emu.database.Database.
    '''

    def __init__(self, logger):
        log.Logger.__init__(self, logger)
        # name -> Filter
        self._filters = dict()
        self._filters['doc_ids'] = DocIdFilter()

    def listen_changes(self, filter_, callback, kwargs=dict()):
        assert callable(callback), ("Callback should be callable, got %r" %
                                    (callback), )

        l_id = str(uuid.uuid1())

        if isinstance(filter_, (list, tuple, )):
            doc_ids = list(filter_)
            filter_i = self._filters['doc_ids']
            filter_i.add_listener(callback, l_id, doc_ids)
            self.log("Registering listener for doc_ids: %r, callback %r",
                     doc_ids, callback)
        elif IViewFactory.providedBy(filter_):
            filter_i = ViewFilter(filter_, kwargs)
            if filter_i.name in self._filters:
                filter_i = self._filters[filter_i.name]
            self._filters[filter_i.name] = filter_i
            filter_i.add_listener(callback, l_id)
        else:
            raise AttributeError("Not suported filter. You should pass a list"
                                 " of document ids or a IViewFactory object "
                                 "passed: %r" % (filter_))
        d = self._setup_notifier(filter_i)
        d.addCallback(defer.override_result, l_id)
        return d

    def cancel_listener(self, listener_id):
        defers = list()
        for filter_i in self._filters.itervalues():
            if filter_i.cancel_listener(listener_id):
                defers.append(self._setup_notifier(filter_i))
        return defer.DeferredList(defers, consumeErrors=True)

    ### protected

    def _setup_notifier(self, filter_):
        # to be overriden in the child classes
        return defer.succeed(None)


class Connection(log.Logger, log.LogProxy):
    '''API for agency to call against the database.'''

    implements(IDatabaseClient, ITimeProvider, IRevisionStore)

    def __init__(self, database):
        log.Logger.__init__(self, database)
        log.LogProxy.__init__(self, database)
        self._database = IDatabaseDriver(database)
        self._serializer = json.Serializer()
        self._unserializer = json.PaisleyUnserializer()

        # listner_id -> doc_ids
        self._listeners = dict()
        self._change_cb = None
        # Changed to use a normal dictionary.
        # It will grow boundless up to the number of documents
        # modified by the connection. It is a kind of memory leak
        # done to temporarily resolve the problem of notifications
        # received after the expiration time due to reconnection
        # killing agents.
        self._known_revisions = {} # {DOC_ID: (REV_INDEX, REV_HASH)}

    ### IRevisionStore ###

    @property
    def known_revisions(self):
        return self._known_revisions

    ### ITimeProvider ###

    def get_time(self):
        return time.time()

    ### IDatabaseClient ###

    def create_database(self):
        return self._database.create_db()

    @defer.inlineCallbacks
    def save_document(self, doc):
        doc = IDocument(doc)

        serialized = self._serializer.convert(doc)
        resp = yield self._database.save_doc(serialized, doc.doc_id)
        self._update_id_and_rev(resp, doc)

        for name, attachment in doc.get_attachments().iteritems():
            if not attachment.saved:
                resp = yield self._database.save_attachment(
                    doc.doc_id, doc.rev, attachment)
                self._update_id_and_rev(resp, doc)
                attachment.set_saved()
        defer.returnValue(doc)

    def get_attachment_body(self, attachment):
        d = self._database.get_attachment(attachment.doc_id, attachment.name)
        return d

    def get_document(self, doc_id):
        d = self._database.open_doc(doc_id)
        d.addCallback(self._unserializer.convert)
        d.addCallback(self._notice_doc_revision)
        return d

    def get_revision(self, doc_id):
        d = self._database.open_doc(doc_id)
        d.addCallback(lambda doc: doc['_rev'])
        return d

    def reload_document(self, doc):
        assert IDocument.providedBy(doc), \
               "Incorrect type: %r, expected IDocument" % (type(doc), )
        return self.get_document(doc.doc_id)

    def delete_document(self, doc):
        assert isinstance(doc, document.Document), type(doc)
        d = self._database.delete_doc(doc.doc_id, doc.rev)
        d.addCallback(self._update_id_and_rev, doc)
        return d

    def changes_listener(self, filter_, callback, **kwargs):
        assert callable(callback)

        r = RevisionAnalytic(self, callback)
        d = self._database.listen_changes(filter_, r.on_change, kwargs)

        def set_listener_id(l_id, filter_):
            self._listeners[l_id] = filter_
            return l_id

        d.addCallback(set_listener_id, filter_)
        return d

    def cancel_listener(self, filter_):
        for l_id, listener_filter in self._listeners.items():
            if ((IViewFactory.providedBy(listener_filter) and
                 filter_ is listener_filter) or
                (isinstance(listener_filter, (list, tuple)) and
                 (filter_ in listener_filter))):
                self._cancel_listener(l_id)

    def query_view(self, factory, **options):
        factory = IViewFactory(factory)
        d = self._database.query_view(factory, **options)
        d.addCallback(self._parse_view_results, factory, options)
        return d

    def disconnect(self):
        if hasattr(self, '_query_cache'):
            self._query_cache.empty()
        for l_id in self._listeners.keys():
            self._cancel_listener(l_id)

    def get_update_seq(self):
        return self._database.get_update_seq()

    def get_changes(self, filter_=None, limit=None, since=0):
        if IViewFactory.providedBy(filter_):
            filter_ = ViewFilter(filter_, params=dict())
        elif filter_ is not None:
            raise ValueError("%r should provide IViewFacory" % (filter_, ))
        return self._database.get_changes(filter_, limit, since)

    def bulk_get(self, doc_ids, consume_errors=True):

        def parse_bulk_response(resp):
            assert isinstance(resp, dict), repr(resp)
            assert 'rows' in resp, repr(resp)

            result = list()
            for doc_id, row in zip(doc_ids, resp['rows']):
                if 'error' in row or 'deleted' in row['value']:
                    if not consume_errors:
                        result.append(NotFoundError(doc_id))
                    else:
                        self.debug("Bulk get parser consumed error row: %r",
                                   row)
                else:
                    result.append(self._unserializer.convert(row['doc']))
            return result


        d = self._database.bulk_get(doc_ids)
        d.addCallback(parse_bulk_response)
        return d

    def get_query_cache(self, create=True):
        '''Called by methods inside feat.database.query module to obtain
        the query cache.
        @param create: C{bool} if True cache will be initialized if it doesnt
                       exist yet, returns None otherwise
        '''

        if not hasattr(self, '_query_cache'):
            if create:
                self._query_cache = query.Cache(self)
            else:
                return None
        return self._query_cache

    ### private

    def _cancel_listener(self, lister_id):
        self._database.cancel_listener(lister_id)
        try:
            del(self._listeners[lister_id])
        except KeyError:
            self.warning('Tried to remove nonexistining listener id %r.',
                         lister_id)

    def _parse_view_results(self, rows, factory, options):
        '''
        rows here should be a list of tuples (key, value)
        rendered by the view
        '''
        reduced = factory.use_reduce and options.get('reduce', True)
        return map(lambda row: factory.parse(row[0], row[1], reduced), rows)

    def _update_id_and_rev(self, resp, doc):
        doc.doc_id = unicode(resp.get('id', None))
        doc.rev = unicode(resp.get('rev', None))
        self._notice_doc_revision(doc)
        return doc

    def _notice_doc_revision(self, doc):
        self.log('Storing knowledge about doc rev. ID: %r, REV: %r',
                 doc.doc_id, doc.rev)
        self._known_revisions[doc.doc_id] = _parse_doc_revision(doc.rev)
        return doc


def _parse_doc_revision(rev):
    rev_index, rev_hash = rev.split("-", 1)
    return int(rev_index), rev_hash


class RevisionAnalytic(log.Logger):
    '''
    The point of this class is to analyze if the document change notification
    has been caused the same or different database connection. It wraps around
    a callback and adds the own_change flag parameter.
    It uses private interface of Connection to get the information of the
    known revisions.
    '''

    def __init__(self, connection, callback):
        log.Logger.__init__(self, connection)
        assert callable(callback), type(callback)

        self.connection = IRevisionStore(connection)
        self._callback = callback

    def on_change(self, doc_id, rev, deleted):
        self.log('Change notification received doc_id: %r, rev: %r, '
                 'deleted: %r', doc_id, rev, deleted)

        own_change = False
        if doc_id in self.connection.known_revisions:
            rev_index, rev_hash = _parse_doc_revision(rev)
            last_index, last_hash = self.connection.known_revisions[doc_id]

            if last_index > rev_index:
                own_change = True

            if (last_index == rev_index) and (last_hash == rev_hash):
                own_change = True

        self._callback(doc_id, rev, deleted, own_change)
