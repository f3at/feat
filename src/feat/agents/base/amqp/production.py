import warnings

from zope.interface import classProvides, implements

from feat.common import serialization, log
from feat.agencies.net import messaging
from feat.agents.base import recipient
from feat.agents.base.amqp.interface import *
from feat.agencies.interface import IMessagingPeer
from feat.agents.base import replay

from feat.interface.channels import IChannelSink


@serialization.register
class AMQPClient(serialization.Serializable, log.Logger, log.LogProxy):
    classProvides(IAMQPClientFactory)
    implements(IAMQPClient, IMessagingPeer, IChannelSink)

    def __init__(self, logger, exchange, exchange_type='fanout',
                 host='localhost', port=5672, vhost='/',
                 user='guest', password='guest'):
        log.Logger.__init__(self, logger)
        log.LogProxy.__init__(self, logger)
        self._backend = None
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
        self._backend = messaging.Messaging(self.host, self.port,
                                            self.user, self.password)
        d = self._backend.new_channel(self)
        d.addCallback(self._store_channel)
        d.addCallback(lambda _: self._setup_exchange())
        return d

    def publish(self, message, key):
        assert self._channel is not None
        recip = recipient.Recipient(key, self.exchange)
        return self._channel.post(recip, message)

    @replay.side_effect
    def disconnect(self):
        self._backend.disconnect()
        self._backend = None
        self._channel = None

    ### IChannelSink ###

    def get_agent_id(self):
        return None

    def get_shard_id(self):
        return None

    def on_message(self, msg):
        pass

    ### IMessagingPeer ###

    def get_queue_name(self):
        warnings.warn("IMessagingPeer's get_queue_name() is deprecated, "
                      "please use IChannelSink's get_agent_id() instead.",
                      DeprecationWarning)
        return self.get_agent_id()

    def get_shard_name(self):
        warnings.warn("IMessagingPeer's get_shard_name() is deprecated, "
                      "please use IChannelSink's get_shard_id() instead.",
                      DeprecationWarning)
        return self.get_shard_id()

    ### private ###

    def _store_channel(self, channel):
        self._channel = channel

    def _setup_exchange(self):
        d = self._channel._define_exchange(self.exchange, self.exchange_type)
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
