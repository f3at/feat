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
    _instance_meta = None
    aspect = None

    __slots__ = ("_instance_meta", )

    ### IMetadata ###

    def get_meta(self, name):
        class_meta = self._class_meta
        items = class_meta.get(name, [])

        if self._instance_meta is not None:
            items.extend(self._instance_meta.get(name, []))

        # try:
        #     print type(self.aspect), type(self), self, self.aspect
        #     aspect_meta = IMetadata(self.aspect)
        #     items.extend(aspect_meta.get_meta(name))
        # except TypeError:
        #     pass

        return items

    def iter_meta_names(self):
        # Get class metadata
        class_meta = self._class_meta
        names = set(class_meta)

        if self._instance_meta is not None:
            names.update(self._instance_meta)

        # try:
        #     aspect_meta = IMetadata(self.aspect)
        #     names.update(aspect_meta.iter_meta_names())
        # except TypeError:
        #     pass

        return iter(names)

    def iter_meta(self, *names):
        class_meta = self._class_meta
        instance_meta = self._instance_meta

        # try:
        #     aspect_meta = IMetadata(self.aspect)
        # except TypeError:
        #     aspect_meta = None

        if not names:
            names = self.iter_meta_names()

        for k in names:
            if k in class_meta:
                for m in class_meta[k]:
                    yield m

            if instance_meta is not None and k in instance_meta:
                for m in instance_meta[k]:
                    yield m

            # if aspect_meta is not None:
            #     for m in aspect_meta.get_meta(k):
            #         yield m

    ### protected ###

    def _put_meta(self, name, value, scheme=None):
        if self._instance_meta is None:
            self._instance_meta = {}
        items = self._instance_meta.setdefault(name, [])
        items.append(MetadataItem(name, value, scheme))

    ### annotations ###

    @classmethod
    def annotate_meta(cls, name, value, scheme=None):
        """@see: feat.models.meta.meta"""
        cls._class_meta.put(name, MetadataItem(name, value, scheme))


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
