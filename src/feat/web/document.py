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
from cStringIO import StringIO
import types

from zope.interface import Interface, Attribute, declarations, interface
from zope.interface import implements, providedBy, adapter as zope_adapter
from twisted.python.failure import Failure

from feat.common import defer, error, adapter


### Errors ###


class DocumentError(error.FeatError):
    default_error_name = "Document Error"


class WriteError(DocumentError):
    default_error_name = "Document Write Error"


class NoWriterFoundError(WriteError):
    default_error_name = "No Document Writer Found"


class BadDocumentError(WriteError):
    default_error_name = "Document Value Error"


class ReadError(DocumentError):
    default_error_name = "Document Read Error"


class NoReaderFoundError(ReadError):
    default_error_name = "No Document Reader Found"


class DocumentFormatError(ReadError):
    default_error_name = "Document Format Error"


### Interfaces ###


class IDocument(Interface):

    mime_type = Attribute("Document negotiated type")
    encoding = Attribute("Document negotiated encoding")
    language = Attribute("Document negotiated language")


class IWritableDocument(IDocument):

    def write(data):
        """Writes a block of data into the document,
        unicode will be encoded in the document encoding."""

    def writelines(sequence):
        """Writes a sequence of lines into the document,
        unicode will be encoded in the document encoding."""


class IReadableDocument(IDocument):

    def read(size=-1, decode=True):
        """Reads a block up to the specified size from the document,
        by default the data is decoded from the document encoding
        but it can be disabled to get the raw data."""

    def readline(size=-1, decode=True):
        """Reads a line up to the a specified size from the document,
        by default the data is decoded from the document encoding
        but it can be disabled to get the raw data."""

    def readlines(sizehint=-1, decode=True):
        """Reads a all the document lines,
        by default the data is decoded from the document encoding
        but it can be disabled to get the raw data."""

    def __iter__():
        """Iterate over the document lines."""


class IReader(Interface):

    def read(doc, *args, **kwargs):
        """Reads an object from a document."""


class IWriter(Interface):

    def write(doc, obj, *args, **kwargs):
        """Write an object to a document."""


class IRegistry(Interface):

    def register_writer(writer, mime_type, iface):
        """Registers a document writer for the specified
        mime-type and object interface."""

    def register_reader(reader, mime_type, iface):
        """Registers a document reader for the specified
        mime-type and object interface."""

    def lookup_writer(mime_type, obj):
        """Lookups a document writer for the specified
        mime-type and object."""

    def lookup_reader(mime_type, iface):
        """Lookups a document writer for the specified
        mime-type and object interface."""

    def read(document, iface, *args, **kwargs):
        """Reads an object with specified interface
        from the specified document."""

    def write(document, obj, *args, **kwargs):
        """Writes the specified object to the specified document."""

    def as_string(obj, mime_type, encoding=None):
        """Converts the specified object to a string
        with specified mime-type and encoding."""

    def from_string(data, iface, mime_type, encoding=None):
        """Extract an object with specified interface form a string
        with specified mime-type and encoding."""


### Base Classes ###


class BaseDocument(object):

    implements(IDocument)

    def __init__(self, mime_type, encoding=None):
        self._mime_type = mime_type
        self._encoding = encoding

    ### IDocument Methods ###

    @property
    def mime_type(self):
        return self._mime_type

    @property
    def encoding(self):
        return self._encoding

    ### Protected Methods ###

    def _encode(self, data):
        if not (isinstance(data, unicode) and self._encoding):
            return data
        return data.encode(self._encoding)

    def _decode(self, data):
        if not self._encoding:
            return data
        return data.decode(self._encoding)


class WritableDocument(BaseDocument):

    implements(IWritableDocument)

    def __init__(self, mime_type, encoding=None):
        BaseDocument.__init__(self, mime_type, encoding)
        self._data = StringIO()

    def get_data(self):
        return self._data.getvalue()

    ### IWriter ###

    def write(self, data):
        self._data.write(self._encode(data))

    def writelines(self, sequence):
        self._data.writelines([self._encode(l) for l in sequence])


class ReadableDocument(BaseDocument):

    implements(IReadableDocument)

    def __init__(self, data, mime_type, encoding=None):
        BaseDocument.__init__(self, mime_type, encoding)
        self._data = StringIO(data)

    def read(self, size=-1, decode=True):
        data = self._data.read(size)
        return self._decode(data) if decode else data

    def readline(self, size=-1, decode=True):
        data = self._data.readline(size)
        return self._decode(data) if decode else data

    def readlines(self, sizehint=-1, decode=True):
        lines = self._data.readlines(sizehint)
        return [self._decode(l) for l in lines] if decode else lines

    def __iter__(self):
        return self

    def next(self):
        return self._decode(self._data.next())


class Registry(object):

    reader_wrapper = None
    writer_wrapper = None

    def __init__(self, base=None):
        if base is not None and not isinstance(base,
                                               zope_adapter.AdapterRegistry):
            raise ValueError(repr(base))
        if base is not None:
            bases = (base, )
        else:
            bases = tuple()
        self._registry = zope_adapter.AdapterRegistry(bases)

    def create_subregistry(self):
        return Registry(self._registry)

    def register_writer(self, writer, mime_type, iface):
        writer = IWriter(writer)
        if isinstance(writer, BaseWriterWrapper):
            # To support adapted function
            assert (writer.registry is None) or (writer.registry is self)
            writer.registry = self

        # deal with class->interface adapters:
        if (iface is not None and # None stands for default adapter
            not isinstance(iface, interface.InterfaceClass)):
            iface = declarations.implementedBy(iface)

        self._registry.register([iface], IWritableDocument,
                                mime_type, writer)
        return writer

    def register_reader(self, reader, mime_type, iface):
        reader = IReader(reader)
        if isinstance(reader, BaseReaderWrapper):
            # To support adapted function
            assert (reader.registry is None) or (reader.registry is self)
            reader.registry = self
        self._registry.register([IReadableDocument], iface,
                                mime_type, reader)
        return reader

    def lookup_writer(self, mime_type, obj):
        req = providedBy(obj)
        writer = self._registry.lookup((req, ), IWritableDocument, mime_type)
        if writer is None:
            return

        if not isinstance(writer, BaseWriterWrapper):
            wrapper = self.writer_wrapper or WriterWrapper
            writer = wrapper(self, writer)

        return writer

    def lookup_reader(self, mime_type, iface):
        global _adapter_registry
        reader = self._registry.lookup1(IReadableDocument, iface, mime_type)
        if reader is None:
            return

        if not isinstance(reader, BaseReaderWrapper):
            wrapper = self.reader_wrapper or ReaderWrapper
            reader = wrapper(self, reader)

        return reader

    def read(self, document, iface, *args, **kwargs):
        """
        Returns a Deferred that fire the read object.
        """
        try:
            document = IReadableDocument(document)
            mime_type = document.mime_type
            reader = self.lookup_reader(mime_type, iface)
            if not reader:
                msg = ("No adapter found to read object %s from %s document"
                       % (iface.__class__.__name__, mime_type))
                raise NoReaderFoundError(msg)
            return reader.read(document, *args, **kwargs)
        except:
            return defer.fail(Failure())

    def write(self, document, obj, *args, **kwargs):
        """
        Returns a Deferred that fire the factory result
        that should be the document.
        """
        try:
            document = IWritableDocument(document)
            mime_type = document.mime_type
            writer = self.lookup_writer(mime_type, obj)
            if not writer:
                msg = ("No adapter found to write object %s to %s document"
                       % (obj.__class__.__name__, mime_type))
                raise NoWriterFoundError(msg)
            return writer.write(document, obj, *args, **kwargs)
        except:
            return defer.fail(Failure())

    def as_string(self, obj, mime_type, encoding=None):
        d = self.write(WritableDocument(mime_type, encoding), obj)
        return d.addCallback(defer.call_param, "get_data")

    def from_string(self, data, iface, mime_type, encoding=None):
        return self.read(ReadableDocument(data, mime_type, encoding), iface)


### Functions ###


def get_registry():
    global _registry
    return _registry


def create_subregistry():
    global _registry
    return _registry.create_subregistry()


def register_writer(writer, mime_type, iface):
    global _registry
    return _registry.register_writer(writer, mime_type, iface)


def register_reader(reader, mime_type, iface):
    global _registry
    return _registry.register_reader(reader, mime_type, iface)


def lookup_writer(mime_type, obj):
    global _registry
    return _registry.lookup_writer(mime_type, obj)


def lookup_reader(mime_type, iface):
    global _registry
    return _registry.lookup_reader(mime_type, iface)


def read(document, iface, *args, **kwargs):
    global _registry
    return _registry.read(document, iface, *args, **kwargs)


def write(document, obj, *args, **kwargs):
    global _registry
    return _registry.write(document, obj, *args, **kwargs)


def as_string(obj, mime_type, encoding=None):
    global _registry
    return _registry.as_string(obj, mime_type, encoding)


def from_string(data, iface, mime_type, encoding=None):
    global _registry
    return _registry.from_string(data, iface, mime_type, encoding)


### Private ###


_registry = Registry()


class BaseWriterWrapper(object):
    """Wrapper for writers allowing synchronous results,
    it protects against thrown exceptions,
    allow chaining/modification of documents
    and ensure it always returns the document."""

    __slots__ = ("registry", "_write_fun")

    implements(IWriter)

    def __init__(self, registry, write_fun):
        self.registry = registry
        self._write_fun = write_fun

    def write(self, doc, obj, *args, **kwargs):
        try:
            d = self._write_fun(doc, obj, *args, **kwargs)

            if (d is None) or (d is doc):
                return defer.succeed(doc)

            if isinstance(d, defer.Deferred):
                return d.addCallback(self._check_writer_result, doc)

            return self.registry.write(doc, d)

        except:

            return defer.fail()

    def _check_writer_result(self, result, doc):
        if (result == None) or (result is doc):
            return doc
        return self.registry.write(doc, result)


class BaseReaderWrapper(object):
    """Allows synchronous reading and protect against exceptions."""

    __slots__ = ("registry", "_read_fun")

    implements(IReader)

    def __init__(self, registry, read_fun):
        self.registry = registry
        self._read_fun = read_fun

    def read(self, doc, *args, **kwargs):
        try:

            d = self._read_fun(doc, *args, **kwargs)

            if not isinstance(d, defer.Deferred):
                return defer.succeed(d)

            return d

        except:

            return defer.fail()


class WriterWrapper(BaseWriterWrapper):

    def __init__(self, registry, writer):
        write_fun = IWriter(writer).write
        BaseWriterWrapper.__init__(self, registry, write_fun)


class ReaderWrapper(BaseReaderWrapper):

    def __init__(self, registry, reader):
        read_fun = IReader(reader).read
        BaseReaderWrapper.__init__(self, registry, read_fun)


@adapter.register(types.FunctionType, IWriter)
class WriterFunctionAdapter(BaseWriterWrapper):

    def __init__(self, write_fun):
        BaseWriterWrapper.__init__(self, None, write_fun)


@adapter.register(types.FunctionType, IReader)
class ReaderFunctionAdapter(BaseReaderWrapper):

    def __init__(self, read_fun):
        BaseReaderWrapper.__init__(self, None, read_fun)
