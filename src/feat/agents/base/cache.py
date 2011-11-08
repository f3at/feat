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
from zope.interface import Interface

from feat.agents.base import replay
from feat.common import log, serialization, fiber, defer

from feat.agencies.interface import NotFoundError
from feat.interface.view import IViewFactory


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


@serialization.register
class DocumentCache(replay.Replayable, log.Logger, log.LogProxy):
    """
    I'm a utility one can keep in his state to keep track of the set of
    documents. I always make sure to have the latest version of the document
    and can trigger callbacks when they change.
    """

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
        log.Logger.__init__(self, self.agent)
        replay.Replayable.restored(self)

    ### public ###

    @replay.journaled
    def load_view(self, state, **params):
        if not state.view_factory:
            raise AttributeError("This function call makes sense only if the"
                                 " cache has been configured to use the view.")
        f = state.agent.query_view(state.view_factory, **params)
        f.add_callback(self._view_loaded)
        f.add_callback(fiber.drop_param, state.agent.register_change_listener,
                       state.view_factory, self._document_changed,
                       **state.filter_params)
        f.add_callback(fiber.drop_param, self.get_document_ids)
        return f

    @replay.immutable
    def get_document_ids(self, state):
        return state.documents.keys()

    @replay.journaled
    def add_document(self, state, doc_id):
        if doc_id in state.documents:
            return fiber.succeed(state.documents[doc_id])
        f = self._update_document(doc_id)
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
        return state.documents[doc_id]

    @replay.mutable
    def forget_document(self, state, doc_id):
        self._delete_doc(doc_id)
        if not state.view_factory:
            state.agent.cancel_change_listener(doc_id)

    ### private ###

    @replay.mutable
    def _view_loaded(self, state, result):
        state.documents.clear()
        fibers = [self._update_document(doc_id) for doc_id in result]
        return fiber.FiberList(fibers, consumeErrors=True).succeed()

    @replay.immutable
    def _update_document(self, state, doc_id):
        f = state.agent.get_document(doc_id)
        f.add_callback(self._success_on_get)
        return f

    @replay.mutable
    def _success_on_get(self, state, doc):
        state.documents[doc.doc_id] = doc
        return doc

    @replay.mutable
    def _delete_doc(self, state, doc_id):
        state.documents.pop(doc_id, None)

    @replay.journaled
    def _document_changed(self, state, doc_id, rev, deleted, own_change):
        if deleted:
            self._delete_doc(doc_id)
            if state.listener:
                state.listener.on_document_deleted(doc_id)
        else:
            f = self._update_document(doc_id)
            if state.listener:
                f.add_callback(state.listener.on_document_change)
            f.add_callback(fiber.override_result, None)
            return f
