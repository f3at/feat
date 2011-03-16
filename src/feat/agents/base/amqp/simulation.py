from zope.interface import classProvides, implements

from feat.common import serialization, log, defer
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

        # key -> messages
        self.messages = dict()

    ### IAMQPClient methods ###

    def initiate(self):
        return defer.succeed(None)

    def publish(self, message, key):
        if key not in self.messages:
            self.messages[key] = list()
        self.messages[key].append(message)
        return defer.succeed(None)

    @replay.side_effect
    def disconnect(self):
        pass

    # private

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
