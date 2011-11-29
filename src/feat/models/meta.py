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
from zope.interface import implements

from feat.common import annotate, container

from feat.models.interface import IMetadata, NotSupported, IMetadataItem


def meta(name, value, scheme=None):
    """
    Adds meta information to a class definition.
    @param name: name of the meta data class
    @type name: str or unicode
    @param value: metadata value
    @type value: str or unicode
    @param scheme: format information about the value
    @type scheme: str or unicode or None
    """
    annotate.injectClassCallback("meta", 3, "annotate_meta",
                                 name, value, scheme=scheme)


class Metadata(annotate.Annotable):
    """I add metadata publishing to another class.
    @see: feat.models.interface.IMetadata"""

    implements(IMetadata)

    _class_meta = container.MroDictOfList("_mro_meta")

    __slots__ = ("_instance_meta", )

    ### IMetadata ###

    def get_meta(self, name):
        class_meta = self._class_meta
        items = class_meta.get(name, [])

        if hasattr(self, "_instance_meta"):
            items.extend(self._instance_meta.get(name, []))

        return items

    def iter_meta_names(self):
        # Get class metadata
        class_meta = self._class_meta
        names = set(class_meta)

        if hasattr(self, "_instance_meta"):
            names.update(self._instance_meta)

        return iter(names)

    def iter_meta(self, *names):
        class_meta = self._class_meta
        instance_meta = getattr(self, "_instance_meta", {})

        if not names:
            names = self.iter_meta_names()

        for k in names:
            if k in class_meta:
                for m in class_meta[k]:
                    yield m

            if k in instance_meta:
                for m in instance_meta[k]:
                    yield m

    ### public ###

    def put_meta(self, name, value, scheme=None):
        item = MetadataItem(name, value, scheme)
        self._put_meta(item.name, item)

    def apply_instance_meta(self, meta):
        self._apply_meta(meta, self._put_meta)

    ### private ###

    def _put_meta(self, name, item):
        if not hasattr(self, "_instance_meta"):
            self._instance_meta = {}
        self._instance_meta.setdefault(name, []).append(item)

    ### annotations ###

    @classmethod
    def annotate_meta(cls, name, value, scheme=None):
        """@see: feat.models.meta.meta"""
        item = MetadataItem(name, value, scheme)
        cls._class_meta.put(item.name, item)

    ### class methods ###

    @classmethod
    def apply_class_meta(cls, meta):
        cls._apply_meta(meta, cls._class_meta.put)

    @classmethod
    def _apply_meta(cls, meta, fun):
        if meta is None:
            return
        if not isinstance(meta, list):
            meta = [meta]
        for args in meta:
            item = MetadataItem(*args)
            fun(item.name, item)


class MetadataItem(object):
    """An item of metadata.
    @see: feat.models.interface.IMetadataIdtem"""

    implements(IMetadataItem)

    def __init__(self, name, value, scheme=None):
        self._name = unicode(name)
        self._value = unicode(value)
        self._scheme = unicode(scheme) if scheme is not None else None

    ### IMetadataItem ###

    @property
    def name(self):
        return self._name

    @property
    def value(self):
        return self._value

    @property
    def scheme(self):
        return self._scheme

    ### public ###

    def __repr__(self):
        return "<MetadataItem %s: %s>" % (self._name, self._value)

    def __hash__(self):
        return hash(self._name) ^ hash(self._value) ^ hash(self._scheme)

    def __eq__(self, other):
        try:
            o = IMetadataItem(other)
            return (self._name == o.name
                    and self._value == o.value
                    and self._scheme == o.scheme)
        except TypeError:
            return NotSupported

    def __ne__(self, other):
        res = self.__eq__(other)
        if res == NotSupported:
            return res
        return not res
