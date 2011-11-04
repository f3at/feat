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

    def __init__(self, patron, listener=None):
        log.LogProxy.__init__(self, patron)
        log.Logger.__init__(self, self)
        replay.Replayable.__init__(self, patron, listener)

    def init_state(self, state, agent, listener):
        state.agent = agent
        state.listener = listener and IDocumentChangeListener(listener)
        # doc_id -> document
        state.documents = dict()

    @replay.immutable
    def restored(self, state):
        log.LogProxy.__init__(self, state.agent)
        log.Logger.__init__(self, self.agent)
        replay.Replayable.restored(self)

    ### public ###

    @replay.immutable
    def add_document(self, state, doc_id):
        if doc_id in state.documents:
            return fiber.succeed(state.documents[doc_id])
        d = self._update_document(doc_id)
        d.addCallback(defer.bridge_param,
                      state.agent.register_change_listener,
                      doc_id, self._document_changed)
        return d

    @replay.immutable
    def get_document(self, state, doc_id):
        if doc_id not in state.documents:
            raise NotFoundError(
                "Document with id: %r not in cache." % (doc_id, ))
        return state.documents[doc_id]

    @replay.mutable
    def forget_document(self, state, doc_id):
        self._delete_doc(doc_id)
        state.agent.cancel_change_listener(doc_id)

    ### private ###

    @replay.immutable
    def _update_document(self, state, doc_id):
        d = state.agent.get_document(doc_id)
        d.addCallback(self._success_on_get)
        return d

    @replay.mutable
    def _success_on_get(self, state, doc):
        state.documents[doc.doc_id] = doc
        return doc

    @replay.mutable
    def _delete_doc(self, state, doc_id):
        state.documents.pop(doc_id, None)

    @replay.immutable
    def _document_changed(self, state, doc_id, rev, deleted, own_change):
        if deleted:
            self._delete_doc(doc_id)
            if state.listener:
                state.listener.on_document_deleted(doc_id)
        else:
            d = self._update_document(doc_id)
            if state.listener:
                d.addCallback(state.listener.on_document_change)
            d.addCallback(defer.override_result, None)
            return d
