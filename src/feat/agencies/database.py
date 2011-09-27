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

from twisted.internet import reactor
from zope.interface import implements

from feat.common import log, container, defer, time
from feat.common.serialization import json
from feat.agents.base import document

from feat.agencies.interface import IDatabaseClient, IDatabaseDriver
from feat.interface.generic import *
from feat.interface.view import *


class ChangeListener(log.Logger):
    '''
    Base class for .net.database.Database and emu.database.Database.
    '''

    def __init__(self, logger):
        log.Logger.__init__(self, logger)
        # id -> [(callback, listener_id)]
        self._listeners = {}

    def listen_changes(self, doc_ids, callback):
        assert callable(callback)
        assert isinstance(doc_ids, (list, tuple, ))
        l_id = str(uuid.uuid1())
        self.log("Registering listener for doc_ids: %r, callback %r",
                 doc_ids, callback)
        for doc_id in doc_ids:
            cur = self._listeners.get(doc_id, list())
            cur.append((callback, l_id, ))
            self._listeners[doc_id] = cur
        return defer.succeed(l_id)

    def cancel_listener(self, listener_id):
        for values in self._listeners.itervalues():
            iterator = (x for x in values if x[1] == listener_id)
            for matching in iterator:
                values.remove(matching)

    ### protected

    def _extract_doc_ids(self):
        return list(doc_id for doc_id, value in self._listeners.iteritems()
                    if len(value) > 0)

    def _trigger_change(self, doc_id, rev):
        listeners = self._listeners.get(doc_id, list())
        for cb, _ in listeners:
            reactor.callLater(0, cb, doc_id, rev) #@UndefinedVariable


class Connection(log.Logger):
    '''API for agency to call against the database.'''

    implements(IDatabaseClient, ITimeProvider)

    def __init__(self, database):
        log.Logger.__init__(self, database)
        self._database = IDatabaseDriver(database)
        self._serializer = json.Serializer()
        self._unserializer = json.PaisleyUnserializer()

        self._listener_id = None
        self._change_cb = None
        # Changed to use a normal dictionary.
        # It will grow boundless up to the number of documents
        # modified by the connection. It is a kind of memory leak
        # done to temporarily resolve the problem of notifications
        # received after the expiration time due to reconnection
        # killing agents.
        self._known_revisions = {} # {DOC_ID: (REV_INDEX, REV_HASH)}

    ### ITimeProvider

    def get_time(self):
        return time.time()

    ### IDatabaseClient

    def create_database(self):
        return self._database.create_db()

    def save_document(self, doc):
        serialized = self._serializer.convert(doc)
        d = self._database.save_doc(serialized, doc.doc_id)
        d.addCallback(self._update_id_and_rev, doc)
        return d

    def get_document(self, doc_id):
        d = self._database.open_doc(doc_id)
        d.addCallback(self._unserializer.convert)
        d.addCallback(self._notice_doc_revision)
        return d

    def reload_document(self, doc):
        assert isinstance(doc, document.Document)
        return self.get_document(doc.doc_id)

    def delete_document(self, doc):
        assert isinstance(doc, document.Document)
        d = self._database.delete_doc(doc.doc_id, doc.rev)
        d.addCallback(self._update_id_and_rev, doc)
        return d

    def changes_listener(self, doc_ids, callback):
        assert isinstance(doc_ids, (tuple, list, ))
        assert callable(callback)
        self._change_cb = callback
        d = self._database.listen_changes(doc_ids, self._on_change)

        def set_listener_id(l_id):
            self._listener_id = l_id

        d.addCallback(set_listener_id)
        return d

    def query_view(self, factory, **options):
        factory = IViewFactory(factory)
        d = self._database.query_view(factory, **options)
        d.addCallback(self._parse_view_results, factory, options)
        return d

    def disconnect(self):
        if self._listener_id:
            self._database.cancel_listener(self._listener_id)
            self._listener_id = None
            self._change_cb = None

    ### private

    def _parse_view_results(self, rows, factory, options):
        '''
        rows here should be a list of tuples (key, value)
        rendered by the view
        '''
        reduced = factory.use_reduce and options.get('reduce', True)
        return map(lambda row: factory.parse(row[0], row[1], reduced), rows)

    def _on_change(self, doc_id, rev):
        self.log('Change notification received doc_id: %r, rev: %r',
                 doc_id, rev)

        # FIXME: This should be done in higher levels
        if doc_id in self._known_revisions:
            rev_index, rev_hash = self._parse_doc_revision(rev)
            last_index, last_hash = self._known_revisions[doc_id]

            if last_index > rev_index:
                self.log("Ignoring old change notification for "
                         "document %s revision %s", doc_id, rev)
                return

            if (last_index == rev_index) and (last_hash == rev_hash):
                self.log("Ignoring last change notificatigon for "
                         "document %s revision %s", doc_id, rev)
                return

        if callable(self._change_cb):
            self._change_cb(doc_id, rev)

    def _update_id_and_rev(self, resp, doc):
        doc.doc_id = unicode(resp.get('id', None))
        doc.rev = unicode(resp.get('rev', None))
        self._notice_doc_revision(doc)
        return doc

    def _notice_doc_revision(self, doc):
        self.log('Storing knowledge about doc rev. ID: %r, REV: %r',
                 doc.doc_id, doc.rev)
        # FIXME: This should be done in other way, agent mediums already
        #        know and store this information
        self._known_revisions[doc.doc_id] = self._parse_doc_revision(doc.rev)
        return doc

    def _parse_doc_revision(self, rev):
        rev_index, rev_hash = rev.split("-", 1)
        return int(rev_index), rev_hash
