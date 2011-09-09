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
from __future__ import absolute_import

from cStringIO import StringIO

from twisted.spread import banana

from feat.common.serialization import sexp
from feat.interface.serialization import *


class BananaCodec(object):

    def __init__(self):
        self._banana = banana.Banana()
        self._banana.connectionMade()
        self._banana._selectDialect("pb") # More compact

    def encode(self, lst):
        io = StringIO()
        self._banana.transport = io
        self._banana.sendEncoded(lst)
        return io.getvalue()

    def decode(self, data):
        heap = []
        self._banana.expressionReceived = heap.append
        try:
            self._banana.dataReceived(data)
        finally:
            self._banana.buffer = ''
            del self._banana.expressionReceived
        return heap[0]


class Serializer(sexp.Serializer, BananaCodec):

    def __init__(self, externalizer=None, source_ver=None, target_ver=None):
        sexp.Serializer.__init__(self, externalizer=externalizer,
                                 source_ver=source_ver, target_ver=target_ver)
        BananaCodec.__init__(self)

    ### Overridden Methods ###

    def post_convertion(self, data):
        return self.encode(data)


class Unserializer(sexp.Unserializer, BananaCodec):

    def __init__(self, registry=None, externalizer=None,
                 source_ver=None, target_ver=None):
        sexp.Unserializer.__init__(self, registry=registry,
                                   externalizer=externalizer,
                                   source_ver=source_ver,
                                   target_ver=target_ver)
        BananaCodec.__init__(self)

    ### Overridden Methods ###

    def pre_convertion(self, data):
        return self.decode(data)


def serialize(value):
    global _serializer
    return _serializer.convert(value)


def freeze(value):
    global _serializer
    return _serializer.freeze(value)


def unserialize(data):
    global _unserializer
    return _unserializer.convert(data)


### Private Stuff ###

_serializer = Serializer()
_unserializer = Unserializer()
