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
import inspect
import uuid
import urllib

from twisted.internet import reactor
from twisted.python import failure
from zope.interface import implements

from feat.common import log, defer, time, journal, serialization, error
from feat.common.serialization import json
from feat.database import document, query, common

from feat.database.interface import IDatabaseClient, IDatabaseDriver
from feat.database.interface import IRevisionStore, IDocument, IViewFactory
from feat.database.interface import NotFoundError, ConflictResolutionStrategy
from feat.database.interface import ResignFromModifying, ConflictError
from feat.database.interface import IVersionedDocument, NotMigratable
from feat.interface.generic import ITimeProvider
from feat.interface.serialization import ISerializable


class ViewFilter(object):

    def __init__(self, view, params):
        self.view = view
        self._request = dict(query=params)
        self.name = '?'.join([self.view.name, urllib.urlencode(params)])
        # listener_id -> callback
        self._listeners = dict()

    def match(self, doc):
        # used only by emu
        return self.view.perform_filter(doc, self._request)

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

    type_name = 'db-connection'

    implements(IDatabaseClient, ITimeProvider, IRevisionStore, ISerializable)

    def __init__(self, database, unserializer=None):
        log.Logger.__init__(self, database)
        log.LogProxy.__init__(self, database)
        self._database = IDatabaseDriver(database)
        self._serializer = json.Serializer(sort_keys=True, force_unicode=True)
        self._unserializer = (unserializer or common.CouchdbUnserializer())


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
        # If the counter of current tasks on database which can produce
        # a new revision
        self._update_lock_counter = 0
        # Unlocked callbacks
        self._unlocked_callbacks = set()

        # set([doc_id, rev]), This is used to trigger the asynchronous hook
        # of the document upgrade only ones
        self._upgrades_ran = set()

    ### IRevisionStore ###

    @property
    def known_revisions(self):
        return self._known_revisions

    @property
    def analyzes_locked(self):
        return self._update_lock_counter > 0

    def wait_unlocked(self, callback):
        self._unlocked_callbacks.add(callback)

    ### private used for locking and unlocking the updates ###

    def _lock_notifications(self):
        self._update_lock_counter += 1

    def _unlock_notifications(self):
        assert self._update_lock_counter > 0, "Lock value dropped below 0!"
        self._update_lock_counter -= 1
        if self._update_lock_counter == 0:
            u = self._unlocked_callbacks
            self._unlocked_callbacks = set()
            for callback in u:
                callback()

    ### ITimeProvider ###

    def get_time(self):
        return time.time()

    ### IDatabaseClient ###

    @property
    def database(self):
        return self._database

    @serialization.freeze_tag('IDatabaseClient.create_database')
    def create_database(self):
        return self._database.create_db()

    @serialization.freeze_tag('IDatabaseClient.save_document')
    @defer.inlineCallbacks
    def save_document(self, doc):
        assert IDocument.providedBy(doc) or isinstance(doc, dict), repr(doc)
        try:
            self._lock_notifications()

            serialized = self._serializer.convert(doc)
            if IDocument.providedBy(doc):
                following_attachments = dict(
                    (name, attachment) for name, attachment
                    in doc.get_attachments().iteritems()
                    if not attachment.saved)
                doc_id = doc.doc_id
            else:
                following_attachments = dict()
                doc_id = doc.get('_id')
            resp = yield self._database.save_doc(serialized, doc_id,
                                                 following_attachments)
            self._update_id_and_rev(resp, doc)
            for attachment in following_attachments.itervalues():
                attachment.set_saved()

            # now process all the documents which have been registered to
            # be saved together with this document
            if IDocument.providedBy(doc):
                while doc.links.to_save:
                    to_link, linker_roles, linkee_roles = (
                        doc.links.to_save.pop(0))
                    to_link.links.create(doc=doc, linker_roles=linker_roles,
                                         linkee_roles=linkee_roles)
                    yield self.save_document(to_link)

            defer.returnValue(doc)
        finally:
            self._unlock_notifications()

    @serialization.freeze_tag('IDatabaseClient.get_attachment_body')
    def get_attachment_body(self, attachment):
        d = self._database.get_attachment(attachment.doc_id, attachment.name)
        return d

    @serialization.freeze_tag('IDatabaseClient.get_document')
    def get_document(self, doc_id, raw=False, **extra):
        d = self._database.open_doc(doc_id, **extra)
        if not raw:
            d.addCallback(self.unserialize_document)
        d.addCallback(self._notice_doc_revision)
        return d

    @serialization.freeze_tag('IDatabaseClient.update_document')
    def update_document(self, _doc, _method, *args, **kwargs):
        return self.update_document_ex(_doc, _method, args, kwargs)

    @serialization.freeze_tag('IDatabaseClient.update_document_ex')
    def update_document_ex(self, doc, _method, args=tuple(), keywords=dict()):
        if not IDocument.providedBy(doc):
            d = self.get_document(doc)
        else:
            d = defer.succeed(doc)
        d.addCallback(self._iterate_on_update, _method, args, keywords)
        return d

    @serialization.freeze_tag('IDatabaseClient.get_revision')
    def get_revision(self, doc_id):
        # FIXME: this could be done by lightweight HEAD request
        d = self._database.open_doc(doc_id)
        d.addCallback(lambda doc: doc['_rev'])
        return d

    @serialization.freeze_tag('IDatabaseClient.reload_database')
    def reload_document(self, doc):
        assert IDocument.providedBy(doc), \
               "Incorrect type: %r, expected IDocument" % (type(doc), )
        return self.get_document(doc.doc_id)

    @serialization.freeze_tag('IDatabaseClient.delete_document')
    def delete_document(self, doc):
        if IDocument.providedBy(doc):
            body = {
                "_id": doc.doc_id,
                "_rev": doc.rev,
                "_deleted": True,
                ".type": unicode(doc.type_name)}
            for field in type(doc)._fields:
                if field.meta('keep_deleted'):
                    body[field.serialize_as] = getattr(doc, field.name)
        elif isinstance(doc, dict):
            body = {
                "_id": doc["_id"],
                "_rev": doc["_rev"],
                "_deleted": True}
        else:
            raise ValueError(repr(doc))

        serialized = self._serializer.convert(body)
        self._lock_notifications()
        d = self._database.save_doc(serialized, body["_id"])
        d.addCallback(self._update_id_and_rev, doc)
        d.addBoth(defer.bridge_param, self._unlock_notifications)
        return d

    @serialization.freeze_tag('IDatabaseClient.copy_document')
    def copy_document(self, doc_or_id, destination_id, rev=None):
        if isinstance(doc_or_id, (str, unicode)):
            doc_id = doc_or_id
        elif IDocument.providedBy(doc_or_id):
            doc_id = doc_or_id.doc_id
        elif isinstance(doc_or_id, dict):
            doc_id = doc_or_id['_id']
        else:
            raise TypeError(type(doc_or_id))
        if not doc_id:
            raise ValueError("Cannot determine doc id from %r" % (doc_or_id, ))
        return self._database.copy_doc(doc_id, destination_id, rev)

    @serialization.freeze_tag('IDatabaseClient.changes_listener')
    def changes_listener(self, filter_, callback, **kwargs):
        assert callable(callback)

        r = RevisionAnalytic(self, callback)
        d = self._database.listen_changes(filter_, r.on_change, kwargs)

        def set_listener_id(l_id, filter_):
            self._listeners[l_id] = filter_
            return l_id

        d.addCallback(set_listener_id, filter_)
        return d

    @serialization.freeze_tag('IDatabaseClient.cancel_listener')
    @journal.named_side_effect('IDatabaseClient.cancel_listener')
    def cancel_listener(self, filter_):
        for l_id, listener_filter in self._listeners.items():
            if ((IViewFactory.providedBy(listener_filter) and
                 filter_ is listener_filter) or
                (isinstance(listener_filter, (list, tuple)) and
                 (filter_ in listener_filter))):
                self._cancel_listener(l_id)

    @serialization.freeze_tag('IDatabaseClient.query_view')
    def query_view(self, factory, parse_results=True, **options):
        factory = IViewFactory(factory)
        d = self._database.query_view(factory, **options)
        if parse_results:
            d.addCallback(self._parse_view_results, factory, options)
        return d

    @serialization.freeze_tag('IDatabaseClient.disconnect')
    @journal.named_side_effect('IDatabaseClient.disconnect')
    def disconnect(self):
        for l_id in self._listeners.keys():
            self._cancel_listener(l_id)

    @serialization.freeze_tag('IDatabaseClient.get_update_seq')
    def get_update_seq(self):
        return self._database.get_update_seq()

    @serialization.freeze_tag('IDatabaseClient.get_changes')
    def get_changes(self, filter_=None, limit=None, since=0):
        if IViewFactory.providedBy(filter_):
            filter_ = ViewFilter(filter_, params=dict())
        elif filter_ is not None:
            raise ValueError("%r should provide IViewFacory" % (filter_, ))
        return self._database.get_changes(filter_, limit, since)

    @serialization.freeze_tag('IDatabaseClient.bulk_get')
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
                    result.append(row['doc'])

            return self.unserialize_list_of_documents(result)

        d = self._database.bulk_get(doc_ids)
        d.addCallback(parse_bulk_response)
        return d

    ### public methods used by update and replication mechanism ###

    def get_database_tag(self):
        '''
        Each feat database has a unique tag which identifies it. Thanks to it
        the mechanism cleaning up the update logs make the difference between
        the changes done locally and remotely. The condition for cleaning
        those up is different.
        '''

        def parse_response(doc):
            self._database_tag = doc['tag']
            return self._database_tag

        def create_new(fail):
            fail.trap(NotFoundError)
            doc = {'_id': doc_id, 'tag': unicode(uuid.uuid1())}
            return self.save_document(doc)

        def conflict_handler(fail):
            fail.trap(ConflictError)
            return self.get_database_tag()


        if not hasattr(self, '_database_tag'):
            doc_id = u'_local/database_tag'
            d = self.get_document(doc_id)
            d.addErrback(create_new)
            d.addErrback(conflict_handler)
            d.addCallback(parse_response)
            return d
        else:
            return defer.succeed(self._database_tag)

    ### ISerializable Methods ###

    def snapshot(self):
        return None

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
        rows here should be a list of tuples:
         - (key, value) for reduce views
         - (key, value, id) for nonreduce views without include docs
         - (key, value, id, doc) for nonreduce with with include docs
        '''
        kwargs = dict()
        kwargs['reduced'] = factory.use_reduce and options.get('reduce', True)
        kwargs['include_docs'] = options.get('include_docs', False)
        # Lines below pass extra arguments to the parsing function if they
        # are expected. These arguments are bound method unserialize() and
        # unserialize_list(). They methods perform the magic of parsing and
        # upgrading if necessary the loaded documents.

        spec = inspect.getargspec(factory.parse_view_result)
        if 'unserialize' in spec.args:
            kwargs['unserialize'] = self.unserialize_document
        if 'unserialize_list' in spec.args:
            kwargs['unserialize_list'] = self.unserialize_list_of_documents
        return factory.parse_view_result(rows, **kwargs)

    def _update_id_and_rev(self, resp, doc):
        if IDocument.providedBy(doc):
            doc.doc_id = unicode(resp.get('id', None))
            doc.rev = unicode(resp.get('rev', None))
            self._notice_doc_revision(doc)
        else:
            doc['_id'] = unicode(resp.get('id', None))
            doc['_rev'] = unicode(resp.get('rev', None))
        return doc

    def _notice_doc_revision(self, doc):
        if IDocument.providedBy(doc):
            doc_id = doc.doc_id
            rev = doc.rev
        else:
            doc_id = doc['_id']
            rev = doc['_rev']
        self.log('Storing knowledge about doc rev. ID: %r, REV: %r',
                 doc_id, rev)
        self._known_revisions[doc_id] = _parse_doc_revision(rev)
        return doc

    ### parsing of the documents ###

    def unserialize_document(self, raw):
        doc = self._unserializer.convert(raw)
        if IVersionedDocument.providedBy(doc):
            if doc.has_migrated:
                d = defer.succeed(doc)
                key = (doc.doc_id, doc.rev)
                if key not in self._upgrades_ran:
                    # Make sure that the connection instance only triggers
                    # once asychronous upgrade. This minimizes the amount
                    # of possible conflicts when fetching old document
                    # version more than once.
                    self._upgrades_ran.add(key)
                    for handler, context in doc.get_asynchronous_actions():
                        if handler.use_custom_registry:
                            conn = Connection(self._database,
                                              handler.unserializer)
                        else:
                            conn = self
                        d.addCallback(defer.keep_param, defer.inject_param, 1,
                                      handler.asynchronous_hook, conn, context)
                        d.addErrback(self.handle_immediate_failure,
                                     handler.asynchronous_hook, context)

                    d.addCallback(self.save_document)
                d.addErrback(self.handle_unserialize_failure, raw)
                return d

        return doc

    def handle_immediate_failure(self, fail, hook, context):
        error.handle_failure(self, fail,
                             'Failed calling %r with context %r. ',
                             hook, context)
        return fail

    def handle_unserialize_failure(self, fail, raw):
        type_name = raw.get('.type')
        version = raw.get('.version')

        if fail.check(ConflictError):
            self.debug('Got conflict error when trying to upgrade the '
                       'document: %s version: %s. Refetching it.',
                       type_name, version)
            # probably we've already upgraded it concurrently
            return self.get_document(raw['_id'])

        error.handle_failure(self, fail, 'Asynchronous hooks of '
                             'the upgrade failed. Raising NotMigratable')
        return failure.Failure(NotMigratable((type_name, version, )))

    def unserialize_list_of_documents(self, list_of_raw):
        result = list()
        defers = list()
        for raw in list_of_raw:
            if isinstance(raw, Exception):
                # Exceptions are simply preserved. This behaviour is
                # optionally used by bulk_get().
                d = raw
            else:
                d = self.unserialize_document(raw)
            if isinstance(d, defer.Deferred):
                result.append(None)
                index = len(result) - 1
                d.addCallback(defer.inject_param, 1,
                              result.__setitem__, index)
                defers.append(d)
            else:
                result.append(d)

        if defers:
            d = defer.DeferredList(defers, consumeErrors=True)
            d.addCallback(defer.override_result, result)
            return d
        else:
            return result

    ### private parts of update_document subroutine ###

    def _iterate_on_update(self, _document, _method, args, keywords):
        if IDocument.providedBy(_document):
            doc_id = _document.doc_id
            rev = _document.rev
        else:
            doc_id = _document['_id']
            rev = _document['_rev']

        try:
            result = _method(_document, *args, **keywords)
        except ResignFromModifying:
            return _document
        if result is None:
            d = self.delete_document(_document)
        else:
            d = self.save_document(result)
        if (IDocument.providedBy(_document) and
            _document.conflict_resolution_strategy ==
            ConflictResolutionStrategy.merge):
            update_log = document.UpdateLog(
                handler=_method,
                args=args,
                keywords=keywords,
                rev_from=rev,
                timestamp=time.time())
            d.addCallback(lambda doc:
                          defer.DeferredList([defer.succeed(doc),
                                              self.get_database_tag(),
                                              self.get_update_seq()]))
            d.addCallback(self._log_update, update_log)
        d.addErrback(self._errback_on_update, doc_id,
                     _method, args, keywords)
        return d

    def _log_update(self, ((_s1, doc), (_s2, tag), (_s3, seq)), update_log):
        update_log.rev_to = doc.rev
        update_log.owner_id = doc.doc_id
        update_log.seq_num = seq
        update_log.partition_tag = tag

        d = self.save_document(update_log)
        d.addCallback(defer.override_result, doc)
        return d

    def _errback_on_update(self, fail, doc_id, _method, args, keywords):
        fail.trap(ConflictError)
        d = self.get_document(doc_id)
        d.addCallback(self._iterate_on_update, _method, args, keywords)
        return d


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
        self._buffer = list()

    def on_change(self, doc_id, rev, deleted):
        self.log('Change notification received doc_id: %r, rev: %r, '
                 'deleted: %r', doc_id, rev, deleted)
        if self.connection.analyzes_locked:
            self.connection.wait_unlocked(self.unlocked)
            self._buffer.append((doc_id, rev, deleted))
        else:
            self.process_change(doc_id, rev, deleted)

    def unlocked(self):
        while len(self._buffer) > 0:
            self.process_change(*self._buffer.pop(0))

    def process_change(self, doc_id, rev, deleted):
        own_change = False
        if doc_id in self.connection.known_revisions:
            rev_index, rev_hash = _parse_doc_revision(rev)
            last_index, last_hash = self.connection.known_revisions[doc_id]

            if last_index > rev_index:
                own_change = True

            if (last_index == rev_index) and (last_hash == rev_hash):
                own_change = True

        self._callback(doc_id, rev, deleted, own_change)
