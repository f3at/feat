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

    def __init__(self, externalizer=None):
        sexp.Serializer.__init__(self, externalizer=externalizer)
        BananaCodec.__init__(self)

    ### Overridden Methods ###

    def post_convertion(self, data):
        return self.encode(data)


class Unserializer(sexp.Unserializer, BananaCodec):

    def __init__(self, registry=None, externalizer=None):
        sexp.Unserializer.__init__(self, registry=registry,
                                   externalizer=externalizer)
        BananaCodec.__init__(self)

    ### Overridden Methods ###

    def pre_convertion(self, data):
        return self.decode(data)
