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
from zope.interface import implements, classProvides

from feat.common import formatable, serialization
from feat.common.serialization.json import VERSION_ATOM

from feat.database.interface import IDocument, IVersionedDocument
from feat.database.interface import IDocumentPrivate, IAttachment
from feat.database.interface import NotFoundError
from feat.database.interface import IAttachmentPrivate, DataNotAvailable
from feat.interface.serialization import ISerializable, IRestorator


field = formatable.field


class Document(formatable.Formatable):

    implements(IDocument, IDocumentPrivate)

    ### IDocument ###

    field('doc_id', None, '_id')
    field('rev', None, '_rev')

    @property
    def attachments(self):
        self._init_attachments()
        return self._public_attachments

    def create_attachment(self, name, body, content_type='text/plain'):
        self._init_attachments()
        priv = _Attachment(self.doc_id, name, body, content_type)
        pub = priv.to_public()
        self._attachments[name] = priv
        self._public_attachments[name] = pub
        return pub

    def delete_attachment(self, name):
        self._init_attachments()
        if name not in self._attachments:
            raise NotFoundError("Uknown attachment %s" % (name, ))
        del self._attachments[name]
        del self._public_attachments[name]

    ### IDocumentPrivate ###

    def get_attachments(self):
        self._init_attachments()
        return self._attachments

    ### ISerializable ###

    def recover(self, snapshot):
        if '_attachments' in snapshot:
            self._init_attachments()
            for name, payload in snapshot.pop('_attachments').iteritems():
                s = dict(payload)
                s.update(name=name, doc_id=snapshot.get('_id'))
                a = _Attachment.restore(s)
                self._attachments[name] = a
                self._public_attachments[name] = a.to_public()
        return formatable.Formatable.recover(self, snapshot)

    def snapshot(self):
        res = formatable.Formatable.snapshot(self)
        if hasattr(self, '_attachments'):
            res['_attachments'] = dict()
            for name, attachment in self._attachments.iteritems():
                if not attachment.saved:
                    continue
                res['_attachments'][name] = attachment.snapshot()
        return res

    ### private ###

    def _init_attachments(self):
        if not hasattr(self, '_attachments'):
            self._attachments = dict()
            self._public_attachments = dict(
                (k, v.to_public())
                for k, v in self._attachments.iteritems())


@serialization.register
class Attachment(serialization.Serializable):

    implements(IAttachment)

    type_name = 'attachment'

    def __init__(self, doc_id, name):
        if doc_id is None:
            raise ValueError("Attachments should be created on already saved "
                             "document. Overwise we cannot know their _id. "
                             "If you really need this, set the doc_id of the "
                             "document by hand first.")
        self.doc_id = unicode(doc_id)
        self.name = unicode(name)


class _Attachment(object):

    implements(ISerializable, IAttachmentPrivate)
    classProvides(IRestorator)

    def __init__(self, doc_id, name, body, content_type):
        self._name = name
        self._body = body
        self._content_type = content_type
        self._saved = False
        self._length = None
        self._doc_id = doc_id

    ### IAttachmentPrivate ###

    @property
    def name(self):
        return self._name

    @property
    def saved(self):
        return self._saved

    @property
    def length(self):
        if self.has_body:
            return len(self._body)
        else:
            return self._length

    @property
    def content_type(self):
        return self._content_type

    @property
    def has_body(self):
        return self._body is not None

    def get_body(self):
        if not self.has_body:
            raise DataNotAvailable(self.name)
        return self._body

    def to_public(self):
        return Attachment(self._doc_id, self.name)

    def set_body(self, body):
        self._body = body

    def set_saved(self):
        self._saved = True

    ### ISerializable ###

    def snapshot(self):
        return dict(stub=True, content_type=unicode(self.content_type),
                    length=self.length)

    def recover(self, snapshot):
        self._name = snapshot['name']
        self._body = None
        self._content_type = snapshot['content_type']
        self._saved = True
        self._length = snapshot['length']
        self._doc_id = snapshot['doc_id']
        return self

    def restored(self):
        pass

    ### IRestorator ###

    @classmethod
    def restore(cls, snapshot):
        res = cls.__new__(cls)
        res.recover(snapshot)
        return res


class VersionedDocument(Document):

    implements(IVersionedDocument)

    version = 1

    def snapshot(self):
        snapshot = Document.snapshot(self)
        snapshot[str(VERSION_ATOM)] = type(self).version
        return snapshot
