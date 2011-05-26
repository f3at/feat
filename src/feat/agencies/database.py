# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import time
import uuid

from twisted.internet import reactor
from zope.interface import implements

from feat.common import log, container, defer
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
            reactor.callLater(0, cb, doc_id, rev)


class Connection(log.Logger):
    '''API for agency to call against the database.'''

    implements(IDatabaseClient, ITimeProvider)

    def __init__(self, database):
        log.Logger.__init__(self, database)
        self.database = IDatabaseDriver(database)
        self.serializer = json.Serializer()
        self.unserializer = json.PaisleyUnserializer()

        self.listener_id = None
        self.change_cb = None
        # rev -> doc_id
        self.known_revisions = container.ExpDict(self)

    ### ITimeProvider

    def get_time(self):
        return time.time()

    ### IDatabaseClient

    def create_database(self):
        return self.database.create_db()

    def save_document(self, doc):
        serialized = self.serializer.convert(doc)
        d = self.database.save_doc(serialized, doc.doc_id)
        d.addCallback(self._update_id_and_rev, doc)
        return d

    def get_document(self, id):
        d = self.database.open_doc(id)
        d.addCallback(self.unserializer.convert)
        d.addCallback(self._notice_doc_revision)
        return d

    def reload_document(self, doc):
        assert isinstance(doc, document.Document)
        return self.get_document(doc.doc_id)

    def delete_document(self, doc):
        assert isinstance(doc, document.Document)
        d = self.database.delete_doc(doc.doc_id, doc.rev)
        d.addCallback(self._update_id_and_rev, doc)
        return d

    def changes_listener(self, doc_ids, callback):
        assert isinstance(doc_ids, (tuple, list, ))
        assert callable(callback)
        self.change_cb = callback
        d = self.database.listen_changes(doc_ids, self._on_change)

        def set_listener_id(l_id):
            self.listener_id = l_id
        d.addCallback(set_listener_id)
        return d

    def query_view(self, factory, **options):
        factory = IViewFactory(factory)
        d = self.database.query_view(factory, **options)
        d.addCallback(self._parse_view_results, factory, options)
        return d

    def disconnect(self):
        if self.listener_id:
            self.database.cancel_listener(self.listener_id)
            self.listener_id = None
            self.change_cb = None

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
        key = (doc_id, rev, )
        known = self.known_revisions.get(key, False)
        if known:
            self.log('Ignoring change notification, it is ours.')
        elif callable(self.change_cb):
            self.change_cb(doc_id, rev)

    def _update_id_and_rev(self, resp, doc):
        doc.doc_id = unicode(resp.get('id', None))
        doc.rev = unicode(resp.get('rev', None))
        # store information about rev and doc_id in ExpDict for 1 second
        # so that we can ignore change callback which we trigger
        self._notice_doc_revision(doc)
        return doc

    def _notice_doc_revision(self, doc):
        self.log('Storing knowledge about doc rev. ID: %r, REV: %r',
                 doc.doc_id, doc.rev)
        self.known_revisions.set((doc.doc_id, doc.rev, ), True,
                                 expiration=5, relative=True)
        return doc
