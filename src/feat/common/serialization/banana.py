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
