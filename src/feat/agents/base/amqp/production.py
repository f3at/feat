from zope.interface import classProvides, implements

from feat.common import serialization, log
from feat.agencies.net import messaging
from feat.agents.base.amqp.interface import *
from feat.agencies.interface import IMessagingPeer
from feat.agents.base import replay


@serialization.register
class AMQPClient(serialization.Serializable, log.Logger, log.LogProxy):
    classProvides(IAMQPClientFactory)
    implements(IAMQPClient, IMessagingPeer)

    def __init__(self, logger, exchange, exchange_type='fanout',
                 host='localhost', port=5672, vhost='/',
                 user='guest', password='guest'):
        log.Logger.__init__(self, logger)
        log.LogProxy.__init__(self, logger)
        self._server = None
        self._connection = None

        self.exchange = exchange
        self.exchange_type = exchange_type
        self.host = host
        self.port = port
        self.vhost = vhost
        self.user = user
        self.password = password

    ### IAMQPClient methods ###

    def connect(self):
        assert self._connection is None
        self._server = messaging.Messaging(self.host, self.port,
                                           self.user, self.password)
        d = self._server.get_connection(self)
        d.addCallback(self._store_connection)
        d.addCallback(lambda _: self._setup_exchange())
        return d

    def publish(self, message, key):
        assert self._connection is not None
        return self._connection.publish(key, self.exchange, message)

    @replay.side_effect
    def disconnect(self):
        self._server.disconnect()
        self._server = None
        self._connection = None

    ### IMessagingPeer Methods ###

    def on_message(self, msg):
        pass

    def get_queue_name(self):
        return None

    def get_shard_name(self):
        return None

    ### private ###

    def _store_connection(self, con):
        self._connection = con

    def _setup_exchange(self):
        d = self._connection._messaging.defineExchange(
            self.exchange, self.exchange_type)
        return d

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return self.exchange == other.exchange and\
               self.exchange_type == other.exchange_type and\
               self.host == other.host and\
               self.port == other.port and\
               self.vhost == other.vhost and\
               self.user == other.user and\
               self.password == other.password

    def __ne__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return not self.__eq__(other)
