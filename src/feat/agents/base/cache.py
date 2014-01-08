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
import pprint
import uuid

from twisted.python import failure
from zope.interface import Interface, implements

from feat.agents.base import replay, notifier

from feat.common import log, fiber, defer
from feat.agents.application import feat

from feat.database.interface import NotFoundError, ConflictError, IViewFactory


class IDocumentChangeListener(Interface):

    def on_document_change(self, doc):
        '''
        Callback called when cache notices the new version of the document.
        '''

    def on_document_deleted(self, doc_id):
        '''
        Callback called when cache notices the document from the cache
        has been deleted.
        '''


class IQueueHolder(Interface):

    def next():
        '''
        Returns a tuple of (operation_id, doc_id, args, kwargs, item_id) or
        raises StopIteration.
        '''

    def enqueue(item_id, operation_id, doc_id, args, kwargs):
        '''
        Tells the Queue to append the item to the storage.
        @returns: Fiber.
        '''

    def perform(operation_id, document, args, kwargs):
        '''
        Synchronous method that perfroms a changes on the document.
        It may return the modified version of the document or raise:
         - DeleteDocument - order the document to be deleted.
         - ResignFromModifying - just cancel the change.
        '''

    def on_confirm(item_id):
        '''
        Callback called when the operation is completed. The QueueHolder
        should remove the item corresponding to item_id.
        '''


class DeleteDocument(Exception):
    pass


class ResignFromModifying(Exception):
    pass


@feat.register_restorator
class DocumentCache(replay.Replayable, log.Logger, log.LogProxy):
    """
    I'm a utility one can keep in his state to keep track of the set of
    documents. I always make sure to have the latest version of the document
    and can trigger callbacks when they change.
    """

    ignored_state_keys = ['agent', 'listener']

    application = feat

    def __init__(self, patron, listener=None,
                 view_factory=None, filter_params=None):
        log.LogProxy.__init__(self, patron)
        log.Logger.__init__(self, self)
        replay.Replayable.__init__(self, patron, listener,
                                   view_factory, filter_params)

    def init_state(self, state, agent, listener, view_factory, filter_params):
        state.agent = agent
        state.listener = listener and IDocumentChangeListener(listener)
        # doc_id -> document
        state.documents = dict()

        state.view_factory = view_factory and IViewFactory(view_factory)
        state.filter_params = filter_params or dict()

    @replay.immutable
    def restored(self, state):
        log.LogProxy.__init__(self, state.agent)
        log.Logger.__init__(self, self)
        replay.Replayable.restored(self)

    ### public ###

    @replay.journaled
    def load_view(self, state, **params):
        if not state.view_factory:
            raise AttributeError("This function call makes sense only if the"
                                 " cache has been configured to use the view.")
        f = state.agent.query_view(state.view_factory, include_docs=True,
                                   **params)
        f.add_callback(self._view_loaded)
        f.add_callback(fiber.drop_param, state.agent.register_change_listener,
                       state.view_factory, self._document_changed,
                       **state.filter_params)
        f.add_callback(fiber.drop_param, self.get_document_ids)
        return f

    @replay.mutable
    def cleanup(self, state):
        state.agent.cancel_change_listener(state.view_factory)

    @replay.immutable
    def get_document_ids(self, state):
        return state.documents.keys()

    @replay.journaled
    def add_document(self, state, doc_id):
        if doc_id in state.documents:
            return fiber.succeed(copy.deepcopy(state.documents[doc_id]))
        f = self._refresh_document(doc_id)
        if state.view_factory is None:
            f.add_callback(defer.bridge_param,
                           state.agent.register_change_listener,
                           doc_id, self._document_changed)
        return f

    @replay.immutable
    def get_document(self, state, doc_id):
        if doc_id not in state.documents:
            raise NotFoundError(
                "Document with id: %r not in cache." % (doc_id, ))
        return copy.deepcopy(state.documents[doc_id])

    @replay.immutable
    def save_document(self, state, document):

        def register_listener_if_necessary(doc):
            if doc.doc_id not in self.documents:
                state.agent.register_change_listener(doc.doc_id,
                                                     self._document_changed)
            return doc

        f = state.agent.save_document(document)
        if state.view_factory is None:
            f.add_callback(register_listener_if_necessary)
        f.add_callback(self._store_doc)
        return f

    @replay.immutable
    def delete_document(self, state, document):
        return state.agent.delete_document(document)

    @replay.mutable
    def forget_document(self, state, doc_id):
        self._delete_doc(doc_id)
        if not state.view_factory:
            state.agent.cancel_change_listener(doc_id)

    @replay.journaled
    def refresh_document(self, state, doc_id):
        return self._refresh_document(doc_id)

    ### private ###

    @replay.mutable
    def _view_loaded(self, state, result):
        state.documents = dict((x.doc_id, x) for x in result)

    @replay.immutable
    def _refresh_document(self, state, doc_id):
        f = state.agent.get_document(doc_id)
        f.add_callback(self._store_doc)
        f.add_errback(self._update_not_found, doc_id)
        return f

    @replay.mutable
    def _store_doc(self, state, doc):
        state.documents[doc.doc_id] = doc
        return doc

    @replay.mutable
    def _delete_doc(self, state, doc_id):
        res = state.documents.pop(doc_id, None)
        return res is not None

    @replay.mutable
    def _update_not_found(self, state, fail, doc_id, reraise=True):
        fail.trap(NotFoundError)
        self._delete_doc(doc_id)
        if reraise:
            return fail

    @replay.journaled
    def _document_changed(self, state, doc_id, rev, deleted, own_change):
        if deleted:
            we_had_it = self._delete_doc(doc_id)
            if we_had_it and state.listener:
                state.listener.on_document_deleted(doc_id)
        else:
            should_update = doc_id not in state.documents or \
                            state.documents[doc_id].rev != rev
            f = fiber.succeed()
            if should_update:
                f.add_callback(fiber.drop_param,
                               self._refresh_document, doc_id)
                if state.listener:
                    f.add_callback(state.listener.on_document_change)
            f.add_errback(self._update_not_found, doc_id, reraise=False)
            f.add_callback(fiber.override_result, None)
            return f


@feat.register_restorator
class PersistentUpdater(replay.Replayable, log.Logger, log.LogProxy):
    """
    I'm a utility used for performing the updates of the documents in
    CouchDB minding the concurency. I comunicate with two object passed
    at creation time:
     - queue_holder is the one who is responsible of storing the information
       about the tasks to perform, and performing them
     - cache is holding the documents in memory (DocumentCache instance)
    """

    ignored_state_keys = ['queue_holder', 'cache', 'medium', 'notifier']

    application = feat

    def __init__(self, queue_holder, cache, medium):
        log.LogProxy.__init__(self, cache)
        log.Logger.__init__(self, self)
        replay.Replayable.__init__(self, queue_holder, cache, medium)

    def init_state(self, state, queue_holder, cache, medium):
        state.queue_holder = IQueueHolder(queue_holder)
        state.cache = cache
        # the medium reference here is for AgentNotifier,
        # it uses following method from it:
        # - call_later()
        # - cancel_delayed_call()
        # - warning()
        state.medium = medium

        state.notifier = notifier.AgentNotifier(state.medium)
        state.working = False

    @replay.immutable
    def restored(self, state):
        log.LogProxy.__init__(self, state.cache)
        log.Logger.__init__(self, state.cache)
        replay.Replayable.restored(self)

    @replay.mutable
    def startup(self, state):
        if not state.working:
            state.working = True
            state.medium.call_next(self._startup)

    @replay.journaled
    def update(self, state, doc_id, operation_id, *args, **kwargs):
        item_id = self._uuid()
        f = state.queue_holder.enqueue(item_id, operation_id, doc_id,
                                       args, kwargs)
        f.add_callback(fiber.drop_param, self.startup)
        f.add_callback(fiber.drop_param, state.notifier.wait, item_id)
        return f

    ### private ###

    @replay.side_effect
    def _uuid(self):
        return str(uuid.uuid1())

    @replay.mutable
    def _startup(self, state):
        try:
            f = self._process_next()
            f.add_both(fiber.bridge_param, self._set_working, False)
            f.add_callback(fiber.drop_param, self.startup)
            return f
        except StopIteration:
            self._set_working(False)

    @replay.journaled
    def _process_next(self, state):
        operation_id, doc_id, args, kwargs, item_id = \
                      state.queue_holder.next()

        return self._retry(operation_id, doc_id, args, kwargs, item_id)

    @replay.journaled
    def _retry(self, state, operation_id, doc_id, args, kwargs, item_id):
        f = fiber.succeed(doc_id)
        f.add_callback(state.cache.get_document)
        f.add_both(self._get_document_callback, operation_id,
                   doc_id, args, kwargs, item_id)
        return f

    @replay.mutable
    def _get_document_callback(self, state, result, operation_id,
                               doc_id, args, kwargs, item_id):
        if isinstance(result, failure.Failure):
            document = None
        else:
            document = copy.deepcopy(result)

        try:
            document = state.queue_holder.perform(operation_id,
                                                  document, args, kwargs)
            return self._call_on_cache(
                'save_document', document, operation_id,
                doc_id, args, kwargs, item_id)
        except ResignFromModifying:
            self.log("Not performing %s on doc_id %s, handler resigned.",
                     operation_id, doc_id)
            return self._update_callback(document, item_id)
        except DeleteDocument:
            self.log("Handler %s decided to delete document id: %s",
                     operation_id, doc_id)
            return self._call_on_cache(
                'delete_document', document, operation_id,
                doc_id, args, kwargs, item_id)

    @replay.journaled
    def _call_on_cache(self, state, _method, document, operation_id, doc_id,
                       args, kwargs, item_id):
        method = getattr(state.cache, _method)
        f = method(document)
        f.add_callback(self._update_callback, item_id)
        f.add_errback(self._update_errback, operation_id, doc_id, args,
                      kwargs, item_id)
        return f

    @replay.journaled
    def _update_callback(self, state, document, item_id):
        state.notifier.callback(item_id, document)
        return state.queue_holder.on_confirm(item_id)

    @replay.journaled
    def _update_errback(self, state, fail, operation_id, doc_id, args,
                        kwargs, item_id):
        fail.trap(ConflictError, NotFoundError)

        f = state.cache.refresh_document(doc_id)
        f.add_errback(failure.Failure.trap, NotFoundError)
        f.add_callback(fiber.drop_param, self._retry,
                       operation_id, doc_id, args, kwargs, item_id)
        return f

    @replay.mutable
    def _set_working(self, state, flag):
        state.working = flag


@feat.register_restorator
class DescriptorQueueHolder(replay.Replayable, log.Logger, log.LogProxy):
    """
    I'm an object storing the queue of function calls which will be performed
    against the documents. I persist this information in the agents descriptor
    so that it's not lost between the restarts.
    """

    ignored_state_keys = ['agent']

    application = feat

    implements(IQueueHolder)

    def __init__(self, agent, descriptor_key):
        log.LogProxy.__init__(self, agent)
        log.Logger.__init__(self, self)
        replay.Replayable.__init__(self, agent, descriptor_key)

    def init_state(self, state, agent, descriptor_key):
        state.agent = agent
        state.descriptor_key = descriptor_key

        # list of item_id which have been returned by next but not yet
        # confirmed
        state.prefetched = list()

    @replay.immutable
    def restored(self, state):
        log.LogProxy.__init__(self, state.agent)
        log.Logger.__init__(self, self)
        replay.Replayable.restored(self)

    ### IQueueHolder ###

    @replay.mutable
    def next(self, state):
        desc = state.agent.get_descriptor()
        entries = getattr(desc, state.descriptor_key)
        for o_id, doc_id, args, kwargs, item_id in entries:
            if item_id not in state.prefetched:
                state.prefetched.append(item_id)
                return o_id, doc_id, args, kwargs, item_id
        raise StopIteration()

    @replay.journaled
    def enqueue(self, state, item_id, operation_id, doc_id, args, kwargs):
        return state.agent.update_descriptor(
            self._append, item_id, operation_id, doc_id, args, kwargs)

    @replay.immutable
    def perform(self, state, operation_id, document, args, kwargs):
        method = getattr(state.agent, operation_id)
        return method(document, *args, **kwargs)

    @replay.mutable
    def on_confirm(self, state, item_id):
        if item_id not in state.prefetched:
            self.warning("This is strange! We got confirm() called about "
                         "the item_id %r but it was not prefetched. "
                         "It should never happen.")
        else:
            state.prefetched.remove(item_id)
        return state.agent.update_descriptor(self._remove, item_id)

    ### private ###

    @replay.immutable
    def _append(self, state, desc,
                item_id, operation_id, doc_id, args, kwargs):
        entries = getattr(desc, state.descriptor_key)
        entries.append((operation_id, doc_id, args, kwargs, item_id))

    @replay.immutable
    def _remove(self, state, desc, item_id):
        entries = getattr(desc, state.descriptor_key)
        matching = [x for x in entries if
                    x[4] == item_id]
        for match in matching:
            entries.remove(match)
        if not matching:
            self.warning("We were trying to remove an entry with item_id %r, "
                         "but it's not there. Entries: %s",
                         item_id, pprint.pformat(entries))
