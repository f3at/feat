from feat.common.serialization import json

from feat.database.interface import VERSION_ATOM, CURRENT_VERSION_ATOM
from feat.interface.serialization import IVersionAdapter


class CouchdbUnserializer(json.Unserializer):

    def pre_convertion(self, data):
        # Data coming in is already pre-unserialized by the connection layer.
        # The original unserializer uses simplejson.loads() here to load
        # the data from string.
        return data

    def _adapt_snapshot(self, restorator, snapshot):
        try:
            adapter = IVersionAdapter(restorator)
        except TypeError:
            pass
        else:
            target = getattr(restorator, 'version', None)
            source = snapshot.get(VERSION_ATOM, 1)
            if (target is not None and target != source and
                CURRENT_VERSION_ATOM not in snapshot):
                snapshot = adapter.adapt_version(snapshot, source, target)
        return snapshot
