import uuid

from zope.interface import implements

from feat.common import log, time
from feat.test import common

from feat.agencies.messaging import routing
from feat.agencies import message, recipient

from feat.interface.generic import ITimeProvider


class BaseDummySink(log.Logger):

    implements(routing.ISink)

    key = None
    priority = 0
    final = True

    def __init__(self, logger, table=None, bridge=None, **kwargs):
        log.Logger.__init__(self, logger)
        self.log_name = type(self).__name__

        if 'key' in kwargs:
            self.key = kwargs.pop('key')

        self.table = table
        self.messages = list()

        # table to bridge messages to
        self.bridge = bridge

        self.init()

    def init(self):
        pass

    def create_route(self, **kwargs):
        key = kwargs.pop('key', self.key)
        priority = kwargs.pop('priority', self.priority)
        final = kwargs.pop('final', self.final)

        if kwargs:
            raise AttributeError('Unknown attribute(s): %r' % (kwargs.keys()))

        r = routing.Route(self, key, priority, final)
        return r

    def dispatch(self, message):
        self.messages.append(message)
        return self.table.dispatch(message, outgoing=False)

    ### ISink ###

    def on_message(self, message):
        self.log("Got message, key: %r", message.recipient.key)
        self.messages.append(message)
        if self.bridge:
            self.bridge.dispatch(message)


class Agent(BaseDummySink):

    def init(self):
        if self.key:
            self.recp = recipient.Agent(self.key[0], self.key[1])
        else:
            self.recp = recipient.dummy_agent()
        self.key = self.key or (self.recp.key, self.recp.route)
        self.final = True
        self.interest(self.recp.key, final=True)

    def public_interest(self, key):
        self.interest(key, final=False)

    def interest(self, key, final=False):
        key = (key, 'shard')
        r = self.create_route(key=key, final=final)
        self.table.append_route(r)
        self.bridge.public_interest(key, final=final)

    def on_message(self, message):
        self.log("Got message, key: %r", message.recipient.key)
        self.messages.append(message)


class RabbitMQ(BaseDummySink):

    def init(self):
        self.priority = 100
        self.final = True
        self.table.set_outgoing_sink(self)
        self.bridge.connect(self)

    def public_interest(self, key, final=False):
        pass


class Bridge(BaseDummySink):

    def init(self):
        self._rabbits = list()

    def connect(self, rabbit):
        self._rabbits.append(rabbit)

    def dispatch(self, message):
        self.log('Dispatching in bridge, rabbitmq are: %r', self._rabbits)
        for rabbit in self._rabbits:
            rabbit.dispatch(message)


class MasterBroker(BaseDummySink):

    def init(self):
        self._slaves = dict()
        self.final = True

    def connect(self, slave):
        self.bind_me(slave, slave.key, final=True)

    def on_message(self, message):
        self.log("Got message, key: %r", message.recipient.key)
        key = (message.recipient.key, message.recipient.route)
        if key not in self._slaves:
            self.warning("Don't know what to do, with this message, the key "
                         "is %r, slaves we know: %r",
                         key, self._slaves.keys())
        else:
            [s.dispatch(message) for s in self._slaves[key]]

    def bind_me(self, slave, key, final=True):
        self._append(key, slave)
        self.table.append_route(self.create_route(key=key, priority=1,
                                                  final=final))

    def dispatch(self, message):
        self.messages.append(message)
        return self.table.dispatch(message, outgoing=True)

    def _append(self, key, slave):
        if key not in self._slaves:
            self._slaves[key] = list()
        self._slaves[key].append(slave)


class SlaveBroker(BaseDummySink):

    def init(self):
        self.key = (str(uuid.uuid1()), 'shard')
        self.final = True
        self.table.append_route(self.create_route())
        self.table.set_outgoing_sink(self)

    def public_interest(self, key, final=False):
        self.bridge.bind_me(self, key, final=final)


class Agency(log.LogProxy):

    def __init__(self, logger, bridge=None, master=True, master_broker=None):
        log.LogProxy.__init__(self, logger)
        self.table = routing.Table(self, ITimeProvider(logger))
        if master:
            self.rabbit = RabbitMQ(self, self.table, bridge)
            self.broker = MasterBroker(self, self.table)
        else:
            self.broker = SlaveBroker(self, self.table, master_broker)

    def dispatch(self, message):
        return self.table.dispatch(message)


def direct((key, shard), expiration_time=None):
    recp = recipient.Agent(key, shard)
    return message.BaseMessage(recipient=recp,
                               message_id=str(uuid.uuid1()),
                               expiration_time=expiration_time)


def broadcast(key, shard='shard', expiration_time=None):
    recp = recipient.Broadcast(key, shard)
    return message.BaseMessage(recipient=recp,
                               message_id=str(uuid.uuid1()),
                               expiration_time=expiration_time)


class Host(object):

    def __init__(self, logger, bridge):
        self.logger = logger
        self.master = Agency(logger, bridge)
        self.agents = []
        self.add_agent()
        self.add_agent()
        self.slaves = [Agency(self.logger, master=False,
                              master_broker=self.master.broker)
                       for x in range(2)]
        for s in self.slaves:
            agent = Agent(self.logger, s.table, s.broker)
            self.agents.append(agent)

    def add_agent(self, agent_id=None):
        opts = {}
        if agent_id:
            opts['key'] = agent_id
        agent = Agent(self.logger, self.master.table, self.master.rabbit,
                      **opts)
        self.agents.append(agent)


class TestRouting(common.TestCase):

    implements(ITimeProvider)

    def get_time(self):
        return self._time

    def sleep(self, seconds):
        self._time += seconds

    def setUp(self):
        self._time = time.time()
        bridge = Bridge(self)
        self.hosts = [Host(self, bridge) for x in range(3)]

    def testSendDirectInsideMaster(self):
        host = self.hosts[0]
        m = direct(host.agents[0].key)
        host.master.dispatch(m)
        self.assert_delivered(host.agents[0], m)
        self.assert_not_delivered(host.agents[1], m)
        self.assert_not_delivered(host.agents[2], m)
        self.assert_not_delivered(host.agents[3], m)
        self.assert_not_delivered(host.master.rabbit, m)

    def testSendSlaveToMaster(self):
        host = self.hosts[0]
        m = direct(host.agents[0].key)
        host.slaves[0].dispatch(m)
        self.assert_delivered(host.agents[0], m)
        self.assert_not_delivered(host.agents[1], m)
        self.assert_not_delivered(host.agents[2], m)
        self.assert_not_delivered(host.agents[3], m)
        self.assert_not_delivered(host.master.rabbit, m)

    def testSendDirectMasterToSlave(self):
        host = self.hosts[0]
        m = direct(host.agents[2].key)
        host.master.dispatch(m)
        self.assert_not_delivered(host.agents[0], m)
        self.assert_not_delivered(host.agents[1], m)

        self.assert_delivered(host.agents[2], m)
        self.assert_not_delivered(host.agents[3], m)
        self.assert_not_delivered(host.master.rabbit, m)

    def testSendDirectSlaveToSlave(self):
        host = self.hosts[0]
        m = direct(host.agents[2].key)
        host.slaves[1].dispatch(m)
        self.assert_not_delivered(host.agents[0], m)
        self.assert_not_delivered(host.agents[1], m)
        self.assert_delivered(host.agents[2], m)
        self.assert_not_delivered(host.agents[3], m)
        self.assert_not_delivered(host.master.rabbit, m)

    def testSendOverNetworkMasterToMaster(self):
        m = direct(self.hosts[0].agents[0].key)
        self.hosts[1].master.dispatch(m)
        self.assert_delivered(self.hosts[0].agents[0], m)
        self.assert_not_delivered(self.hosts[0].agents[1], m)
        self.assert_not_delivered(self.hosts[0].agents[2], m)
        self.assert_not_delivered(self.hosts[0].agents[3], m)
        self.assert_delivered(self.hosts[0].master.rabbit, m)

        self.assert_not_delivered(self.hosts[1].agents[0], m)
        self.assert_not_delivered(self.hosts[1].agents[1], m)
        self.assert_not_delivered(self.hosts[1].agents[2], m)
        self.assert_not_delivered(self.hosts[1].agents[3], m)
        self.assert_delivered(self.hosts[1].master.rabbit, m)

    def testSendOverNetworkMasterToSlave(self):
        m = direct(self.hosts[0].agents[2].key)
        self.hosts[1].master.dispatch(m)
        self.assert_not_delivered(self.hosts[0].agents[0], m)
        self.assert_not_delivered(self.hosts[0].agents[1], m)
        self.assert_delivered(self.hosts[0].agents[2], m)
        self.assert_not_delivered(self.hosts[0].agents[3], m)
        self.assert_delivered(self.hosts[0].master.rabbit, m)

        self.assert_not_delivered(self.hosts[1].agents[0], m)
        self.assert_not_delivered(self.hosts[1].agents[1], m)
        self.assert_not_delivered(self.hosts[1].agents[2], m)
        self.assert_not_delivered(self.hosts[1].agents[3], m)
        self.assert_delivered(self.hosts[1].master.rabbit, m)

    def testSendOverNetworkSlaveToSlave(self):
        m = direct(self.hosts[0].agents[2].key)
        self.hosts[1].slaves[0].dispatch(m)
        self.assert_not_delivered(self.hosts[0].agents[0], m)
        self.assert_not_delivered(self.hosts[0].agents[1], m)
        self.assert_delivered(self.hosts[0].agents[2], m)
        self.assert_not_delivered(self.hosts[0].agents[3], m)
        self.assert_delivered(self.hosts[0].master.rabbit, m)

        self.assert_not_delivered(self.hosts[1].agents[0], m)
        self.assert_not_delivered(self.hosts[1].agents[1], m)
        self.assert_not_delivered(self.hosts[1].agents[2], m)
        self.assert_not_delivered(self.hosts[1].agents[3], m)
        self.assert_delivered(self.hosts[1].master.rabbit, m)

    def testBroadcastNooneInterested(self):
        key = 'public-protocol'
        m = broadcast(key)

        self.hosts[0].master.dispatch(m)
        for host in self.hosts:
            self.assert_not_delivered(host.agents[0], m)
            self.assert_not_delivered(host.agents[1], m)
            self.assert_not_delivered(host.agents[2], m)
            self.assert_not_delivered(host.agents[3], m)
            self.assert_delivered(host.master.rabbit, m)

    def testBroadcastWithAgentsInterestedSendFromSlave(self):
        key = 'public-protocol'
        m = broadcast(key)
        self.hosts[0].agents[0].public_interest(key)
        self.hosts[1].agents[3].public_interest(key)
        self.hosts[2].agents[2].public_interest(key)

        self.hosts[0].slaves[0].dispatch(m)

        self.assert_delivered(self.hosts[0].agents[0], m)
        self.assert_not_delivered(self.hosts[0].agents[1], m)
        self.assert_not_delivered(self.hosts[0].agents[2], m)
        self.assert_not_delivered(self.hosts[0].agents[3], m)
        self.assert_delivered(self.hosts[0].master.rabbit, m)

        self.assert_not_delivered(self.hosts[1].agents[0], m)
        self.assert_not_delivered(self.hosts[1].agents[1], m)
        self.assert_not_delivered(self.hosts[1].agents[2], m)
        self.assert_delivered(self.hosts[1].agents[3], m)
        self.assert_delivered(self.hosts[1].master.rabbit, m)

        self.assert_not_delivered(self.hosts[2].agents[0], m)
        self.assert_not_delivered(self.hosts[2].agents[1], m)
        self.assert_delivered(self.hosts[2].agents[2], m)
        self.assert_not_delivered(self.hosts[2].agents[3], m)
        self.assert_delivered(self.hosts[2].master.rabbit, m)

    def testBroadcastWithAgentsInterestedSendFromMaster(self):
        key = 'public-protocol'
        m = broadcast(key)
        self.hosts[0].agents[0].public_interest(key)
        self.hosts[1].agents[3].public_interest(key)
        self.hosts[2].agents[2].public_interest(key)

        self.hosts[2].master.dispatch(m)

        self.assert_delivered(self.hosts[0].agents[0], m)
        self.assert_not_delivered(self.hosts[0].agents[1], m)
        self.assert_not_delivered(self.hosts[0].agents[2], m)
        self.assert_not_delivered(self.hosts[0].agents[3], m)
        self.assert_delivered(self.hosts[0].master.rabbit, m)

        self.assert_not_delivered(self.hosts[1].agents[0], m)
        self.assert_not_delivered(self.hosts[1].agents[1], m)
        self.assert_not_delivered(self.hosts[1].agents[2], m)
        self.assert_delivered(self.hosts[1].agents[3], m)
        self.assert_delivered(self.hosts[1].master.rabbit, m)

        self.assert_not_delivered(self.hosts[2].agents[0], m)
        self.assert_not_delivered(self.hosts[2].agents[1], m)
        self.assert_delivered(self.hosts[2].agents[2], m)
        self.assert_not_delivered(self.hosts[2].agents[3], m)
        self.assert_delivered(self.hosts[2].master.rabbit, m)

    def testBroadcastAndLaterExpressInterest(self):
        key = 'public-protocol'
        m = broadcast(key, expiration_time=self.get_time() + 1)

        self.hosts[0].master.dispatch(m)
        for host in self.hosts:
            self.assert_not_delivered(host.agents[0], m)
            self.assert_not_delivered(host.agents[1], m)
            self.assert_not_delivered(host.agents[2], m)
            self.assert_not_delivered(host.agents[3], m)
            self.assert_delivered(host.master.rabbit, m)

        self.hosts[0].agents[0].public_interest(key)
        self.assert_delivered(self.hosts[0].agents[0], m)

        self.sleep(2)

        self.hosts[1].agents[0].public_interest(key)
        self.assert_not_delivered(self.hosts[1].agents[0], m)

    def testDirectMessageBeforeAgentBinds(self):
        agent_id = 'some_agent'
        key = (agent_id, 'shard')
        m = direct(key, expiration_time=self.get_time() + 1)

        self.hosts[0].master.dispatch(m)
        for host in self.hosts:
            self.assert_not_delivered(host.agents[0], m)
            self.assert_not_delivered(host.agents[1], m)
            self.assert_not_delivered(host.agents[2], m)
            self.assert_not_delivered(host.agents[3], m)
            self.assert_delivered(host.master.rabbit, m)

        self.hosts[0].add_agent(key)
        self.assert_delivered(self.hosts[0].agents[-1], m)

        self.hosts[0].agents[0].public_interest(key)
        self.assert_not_delivered(self.hosts[1].agents[0], m)

    def assert_delivered(self, sink, msg):
        m_id = msg.message_id
        m_ids = [msg.message_id for msg in sink.messages]
        self.assertTrue(m_id in m_ids, "Messages are: %r" % (sink.messages, ))

    def assert_not_delivered(self, sink, msg):
        m_id = msg.message_id
        m_ids = [msg.message_id for msg in sink.messages]
        self.assertFalse(m_id in m_ids, "Messages are: %r" % (sink.messages, ))
