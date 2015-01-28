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
import itertools

from zope.interface import implements, classProvides

from feat.common import formatable, serialization, first
from feat.database import migration, common

from feat.database.interface import IDocument, IVersionedDocument
from feat.database.interface import IDocumentPrivate, IAttachment
from feat.database.interface import NotFoundError, ConflictResolutionStrategy
from feat.database.interface import IAttachmentPrivate, DataNotAvailable
from feat.database.interface import NotMigratable

from feat.interface.serialization import ISerializable, IRestorator
from feat.interface.serialization import IVersionAdapter


VERSION_ATOM = common.VERSION_ATOM
field = formatable.field


class Document(formatable.Formatable):

    implements(IDocument, IDocumentPrivate)
    conflict_resolution_strategy = ConflictResolutionStrategy.db_winner

    ### IDocument ###

    field('doc_id', None, '_id')
    field('rev', None, '_rev')
    # [[type_name, doc_id, [linker_roles], [likee_roles]]]
    field('linked', list())

    @property
    def attachments(self):
        self._init_attachments()
        return self._public_attachments

    def create_attachment(self, name, body, content_type='text/plain',
                          unique=False):
        '''
        @param unique: Defines how to behave if the attachment with this name
                       already exists. If False (default) the attachment is
                       overwritten. If True the name will be addded a suffix
                       to make it unique.
        '''
        self._init_attachments()
        if unique and name in self._attachments:
            splitted = name.split('.', 1)
            tmpl = splitted[0] + '_%d'
            if len(splitted) == 2:
                tmpl += "." + splitted[1]

            index = 1
            while name in self._attachments:
                name = tmpl % (index, )
                index += 1
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

    @property
    def links(self):
        if not hasattr(self, '_linked_documents'):
            self._linked_documents = LinkedDocuments(self.linked)
        return self._linked_documents

    def mark_as_deleted(self):
        self._deleted = True

    def compare_content(self, other):
        '''
        Compare only the content of the documents (ignoring the meta fields).
        '''
        if type(self) is not type(other):
            return False
        s1 = self.snapshot()
        s2 = other.snapshot()
        for snapshot in (s1, s2):
            for key in snapshot.keys():
                if key[0] in ('_', '.'):
                    del snapshot[key]
        return s1 == s2

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
        if snapshot.pop('_deleted', False):
            self._deleted = True
        return formatable.Formatable.recover(self, snapshot)

    def snapshot(self):
        res = formatable.Formatable.snapshot(self)
        if hasattr(self, '_attachments'):
            res['_attachments'] = dict()
            for name, attachment in self._attachments.iteritems():
                res['_attachments'][name] = attachment.snapshot()
        if getattr(self, '_deleted', False):
            res['_deleted'] = True
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
        self.doc_id = doc_id and unicode(doc_id)
        self.name = unicode(name)

    def snapshot(self):
        if self.doc_id is None:
            raise ValueError("Attachments should be created on already saved "
                             "document. Overwise we cannot know their _id. "
                             "If you really need this, set the doc_id of the "
                             "document by hand first.")
        return super(Attachment, self).snapshot()


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
        b = dict(content_type=unicode(self.content_type),
                 length=self.length)
        if self.saved:
            b['stub'] = True
        else:
            b['follows'] = True
        return b

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


class MetaVersionedDocument(type(Document)):

    implements(IVersionAdapter)

    def adapt_version(cls, snapshot, source_ver, target_ver):
        plan = cls.plan_migration(source_ver, target_ver)
        for step in plan:
            res = step.synchronous_hook(snapshot)
            if isinstance(res, tuple) and len(res) == 2:
                snapshot, context = res
            elif isinstance(res, dict):
                snapshot, context = res, None
            else:
                raise ValueError("%r.synchronous_hook() returned sth "
                                 " strange: %r" % (step, res))
            if context is not None:
                snapshot.setdefault('_asynchronous_actions', list())
                snapshot['_asynchronous_actions'].append((step, context))
        snapshot['_has_migrated'] = True
        return snapshot

    def plan_migration(cls, source, target):
        # build up the shortest list of transformations which leads between
        # versions
        middle = range(source + 1, target)
        registry = migration.get_registry()

        for n_divisions in range(target - source):
            # test all the possible paths between revisions in given
            # number of steps
            for division in itertools.combinations(middle, n_divisions):
                s = source
                migrations = list()
                for index in division:
                    m = registry.lookup((cls.type_name, s, index))
                    if not m:
                        break
                    migrations.append(m)
                    s = index
                else:
                    m = registry.lookup((cls.type_name, s, target))
                    if not m:
                        continue
                    migrations.append(m)
                    return migrations
        raise NotMigratable((cls.type_name, source, target))

    def store_version(self, snapshot, version):
        snapshot[str(VERSION_ATOM)] = version
        return snapshot


class VersionedDocument(Document):

    __metaclass__ = MetaVersionedDocument

    implements(IVersionedDocument)

    version = 1

    def snapshot(self):
        snapshot = Document.snapshot(self)
        cls = type(self)
        return cls.store_version(snapshot, cls.version)

    ### IVersionedDocument ###

    def get_asynchronous_actions(self):
        if not hasattr(self, '_asynchronous_actions'):
            return []
        return self._asynchronous_actions

    @property
    def has_migrated(self):
        return getattr(self, '_has_migrated', False)

    ### IRestorator ###

    def recover(self, snapshot):
        if '_asynchronous_actions' in snapshot:
            self._asynchronous_actions = snapshot.pop('_asynchronous_actions')
        if '_has_migrated' in snapshot:
            self._has_migrated = snapshot.pop('_has_migrated')
        super(VersionedDocument, self).recover(snapshot)


@serialization.register
class UpdateLog(VersionedDocument):

    type_name = 'update_log'

    field('seq_num', None)
    field('handler', None)
    field('keywords', dict())
    field('args', tuple())
    field('rev_from', None)
    field('rev_to', None)
    field('owner_id', None)
    field('timestamp', None)
    field('partition_tag', None)


class LinkedDocuments(object):
    '''
    Utility class making sure the format of *doc.links* list is preserved.
    '''

    def __init__(self, links):
        self._links = links
        # list of documents to be saved after the owner of this class is saved
        # format: [(IDocument, linker_roles or None, linkee_roles or None)]
        self.to_save = list()

    def create(self, doc_id=None, linker_roles=None,
               linkee_roles=None, type_name=None, doc=None):
        if doc is not None:
            if IDocument.providedBy(doc):
                doc_id = doc.doc_id or doc_id
                type_name = doc.type_name
            elif isinstance(doc, dict):
                doc_id = doc['_id']
            else:
                raise TypeError(doc)
        if doc_id is None:
            raise ValueError("Either pass doc_id or saved document instance")
        if type_name is None:
            raise ValueError("Type name is needed to create a link")
        if linker_roles and not isinstance(linker_roles, list):
            raise TypeError(linker_roles)
        if linkee_roles and not isinstance(linkee_roles, list):
            raise TypeError(linkee_roles)

        self.remove(doc_id, noraise=True)
        self._links.append([type_name, doc_id,
                            linker_roles or list(), linkee_roles or list()])

    def save_and_link(self, doc, linker_roles=None, linkee_roles=None):
        self.to_save.append((doc, linker_roles, linkee_roles))

    def remove(self, doc_id, noraise=False):
        r = self._get(doc_id, noraise)
        if r:
            self._links.remove(r)

    def first(self, type_name):
        '''
        Return doc_id of the document of the first matching type.
        '''
        return first(self.by_type(type_name))

    def by_type(self, type_name):
        '''
        Return an iterator of doc_ids of the documents of the
        specified type.
        '''
        if IRestorator.providedBy(type_name):
            type_name = type_name.type_name
        return (x[1] for x in self._links if x[0] == type_name)

    def _get(self, doc_id, noraise):
        r = first(x for x in self._links if x[1] == doc_id)
        if not r and not noraise:
            raise KeyError(doc_id)
        return r


### implementation of versioned formatable used inside the documents ###


class MetaVersionedFormatable(type(formatable.Formatable),
                              type(serialization.VersionAdapter)):
    pass


class VersionedFormatable(formatable.Formatable, serialization.VersionAdapter):

    __metaclass__ = MetaVersionedFormatable

    version = 1

    def snapshot(self):
        snapshot = formatable.Formatable.snapshot(self)
        return self.store_version(snapshot, self.version)

    def store_version(self, snapshot, version):
        snapshot[str(VERSION_ATOM)] = version
        return snapshot
