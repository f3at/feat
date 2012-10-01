from zope.interface import implements

from feat.common import serialization, defer
from feat.database import tools, client

from feat.database.interface import IMigration
from feat.interface.serialization import IRestorator


class Migration(object):

    name = None
    unserializer_factory = serialization.json.PaisleyUnserializer

    implements(IMigration)

    def __init__(self):
        # type, callback
        self._handlers = dict()
        self.registry = serialization.get_registry().clone()
        self.unserializer = type(self).unserializer_factory(
            registry=self.registry)

    @defer.inlineCallbacks
    def run(self, database):
        connection = client.Connection(database, self.unserializer)
        for name, callback in self._handlers.items():
            keys = dict(key=name, include_docs=True)
            yield tools.view_aterator(connection, self._handler,
                                      tools.DocumentByType, keys,
                                      args=(name, callback),
                                      consume_errors=False)

    def _handler(self, connection, unparsed, name, callback):
        if callable(callback):
            return callback(connection, unparsed)
        else:
            doc = self.unserializer.convert(unparsed)
            if doc.has_migrated:
                return connection.save_document(doc)

    def migrate_type(self, type, callback=None):
        if IRestorator.providedBy(type):
            type = type.type_name
        self._handlers[type] = callback

    def __repr__(self):
        if self.name:
            return "<Migration: %s>" % (self.name, )
        else:
            return super(Migration, self).__repr__()
