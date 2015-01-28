from feat.common.serialization import json

from feat.database.interface import VERSION_ATOM, CURRENT_VERSION_ATOM


class CouchdbUnserializer(json.Unserializer):

    def pre_convertion(self, data):
        # Data coming in is already pre-unserialized by the connection layer.
        # The original unserializer uses simplejson.loads() here to load
        # the data from string.
        return data

    def get_target_ver(self, restorator, snapshot):
        if CURRENT_VERSION_ATOM not in snapshot:
            return getattr(restorator, 'version', None)

    def get_source_ver(self, restorator, snapshot):
        return snapshot.get(VERSION_ATOM, 1)
