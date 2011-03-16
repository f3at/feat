# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.internet import defer
from twisted.trial.unittest import SkipTest

from feat.test.common import attr, delay, StubAgent
from feat.agencies.emu import messaging as emu_messaging
from feat.agents.base import message
from feat.process import rabbitmq
from feat.process.base import DependencyError


try:
    from feat.agencies.net import messaging
except ImportError as e:
    messaging = None
    import_error = e

from . import common


def m(payload):
    '''
    Wraps the payload into BaseMessage.
    '''
    return message.BaseMessage(payload=payload)


def unwrap(msg):
    '''
    Perform the reverse operation to m().
    '''
    assert isinstance(msg, message.BaseMessage)
    return msg.payload


class TestCase(object):

    number_of_agents = 2

    def _agent(self, n):
        return dict(key=self.agents[n].get_queue_name(), shard='lobby')

    @defer.inlineCallbacks
    def init_agents(self):
        self.agents = [StubAgent() for x in range(self.number_of_agents)]
        self.connections = list()
        bindings = list()
        for agent in self.agents:
            connection = yield self.messaging.get_connection(agent)
            self.connections.append(connection)
            pb = connection.personal_binding(agent.get_queue_name())
            bindings.append(pb)
        yield defer.DeferredList(map(lambda b: b.created, bindings))

    @attr(number_of_agents=2)
    @defer.inlineCallbacks
    def testTwoAgentsTalking(self):
        d = self.cb_after(None, self.agents[1], 'on_message')
        d2 = self.cb_after(None, self.agents[0], 'on_message')
        self.connections[0].publish(message=m("you stupid!"), **self._agent(1))
        yield d
        self.assertEqual(1, len(self.agents[1].messages))
        self.assertEqual('you stupid!', unwrap(self.agents[1].messages[0]))

        self.connections[0].publish(message=m("buzz off"), **self._agent(0))

        yield d2
        self.assertEqual(1, len(self.agents[0].messages))
        self.assertEqual('buzz off', unwrap(self.agents[0].messages[0]))

    @defer.inlineCallbacks
    def testMultipleAgentsWithSameBinding(self):
        key = 'some key'
        bindings = map(lambda x: x.personal_binding(key), self.connections)
        yield defer.DeferredList(map(lambda x: x.created, bindings))

        self.connections[0].publish(message=m('some message'),
                                    key=key, shard='lobby')
        yield defer.DeferredList(map(
            lambda x: self.cb_after(None, method='on_message', obj=x),
                                   self.agents))

        for agent in self.agents:
            self.assertEqual(1, len(agent.messages))

    @defer.inlineCallbacks
    def testTellsDiffrenceBeetweenShards(self):
        shard = 'some shard'
        key = 'some key'
        msg = m("only for connection 0")

        bindings = [self.connections[0].personal_binding(key, shard),
                    self.connections[1].personal_binding(key)]
        yield defer.DeferredList(map(lambda x: x.created, bindings))

        d = self.cb_after(None, obj=self.agents[0], method="on_message")
        yield self.connections[1].publish(message=msg, key=key, shard=shard)
        yield d

        self.assertEqual(0, len(self.agents[1].messages))
        self.assertEqual(1, len(self.agents[0].messages))
        self.assertEqual(msg, self.agents[0].messages[0])

    @defer.inlineCallbacks
    def testRevokedBindingsDontBind(self):
        shard = 'some shard'
        key = 'some key'
        msg = m("only for connection 0")

        bindings = [self.connections[0].personal_binding(key, shard),
                    self.connections[1].personal_binding(key)]
        yield defer.DeferredList(map(lambda x: x.created, bindings))

        yield defer.DeferredList(map(lambda x: x.revoke(), bindings))

        yield self.connections[1].publish(message=msg, key=key, shard=shard)

        yield delay(None, 0.1)

        for agent in self.agents:
            self.assertEqual(0, len(agent.messages))


class RabbitSpecific(object):
    """
    This testcase is specific for RabbitMQ integration, as simulation of
    disconnection doesn't make sense for the emu implementation.
    """

    def disconnect_client(self):
        return self.messaging._connector.disconnect()

    @attr(number_of_agents=10)
    @defer.inlineCallbacks
    def testReconnect(self):
        d1 = self.cb_after(None, self.agents[0], "on_message")
        yield self.connections[1].publish(message=m("first message"),
                                          **self._agent(0))
        yield d1
        yield self.disconnect_client()

        d2 = self.cb_after(None, self.agents[0], "on_message")
        yield self.connections[1].publish(message=m("second message"),
                                          **self._agent(0))
        yield d2

        self.assertEqual(2, len(self.agents[0].messages))
        self.assertEqual("first message", unwrap(self.agents[0].messages[0]))
        self.assertEqual("second message", unwrap(self.agents[0].messages[1]))

    @attr(number_of_agents=3, timeout=20)
    @defer.inlineCallbacks
    def testMultipleReconnects(self):

        def wait_for_msgs():
            return defer.DeferredList(map(
                lambda ag: self.cb_after(None, ag, 'on_message'),
                self.agents))

        def send_to_neighbour(attempt):
            total = len(self.connections)
            deferrs = list()
            for conn, i in zip(self.connections, range(total)):
                target = (i + 1) % total
                msg = "%s,%s" % (attempt, target, )
                d = conn.publish(message=m(msg), **self._agent(target))
                deferrs.append(d)
            return defer.DeferredList(deferrs)

        def asserts(attempt):
            for agent in self.agents:
                self.assertEqual(attempt, len(agent.messages))
                self.assertTrue(
                    unwrap(agent.messages[-1]).startswith("%s," % attempt))

        number_of_reconnections = 5

        yield self.process.rabbitmqctl_dump(
            'list_bindings exchange_name queue_name')

        for index in range(1, number_of_reconnections + 1):
            d = wait_for_msgs()
            yield send_to_neighbour(index)

            self.log('Reconnecting %d time out of %d.',
                     index, number_of_reconnections)

            yield self.disconnect_client()
            yield self.process.rabbitmqctl_dump(
                'list_queues name messages '
                'messages_ready consumers')

            yield d
            yield self.process.rabbitmqctl_dump(
                'list_queues name messages')
            asserts(index)

    @attr(number_of_agents=0)
    @defer.inlineCallbacks
    def testCreatingBindingsOnReadyConnection(self):
        '''
        Checks that creating personal binding after the connection
        has been initialized works the same as during initialization
        time.
        '''
        agent = StubAgent()
        self.agents = [agent]
        connection = yield self.messaging.get_connection(agent)

        # wait for connection to be established
        client = yield connection._messaging.factory.add_connection_made_cb()

        self.assertIsInstance(client, messaging.MessagingClient)
        binding = connection.personal_binding(agent.get_queue_name())
        yield binding.created

        d = self.cb_after(None, agent, 'on_message')
        connection.publish(message=m('something'), **self._agent(0))
        yield d

        self.assertEqual(1, len(agent.messages))


class EmuMessagingIntegrationTest(common.IntegrationTest, TestCase):

    def setUp(self):
        self.messaging = emu_messaging.Messaging()
        return self.init_agents()


@attr('slow')
class RabbitIntegrationTest(common.IntegrationTest, TestCase,
                            RabbitSpecific):

    timeout = 10

    configurable_attributes = ['number_of_agents']

    @defer.inlineCallbacks
    def setUp(self):
        if messaging is None:
            raise SkipTest('Skipping the test because of missing '
                           'dependecies: %r' % import_error)

        try:
            self.process = rabbitmq.Process(self)
        except DependencyError as e:
            raise SkipTest(str(e))

        yield self.process.restart()

        self.messaging = messaging.Messaging(
            '127.0.0.1', self.process.get_config()['port'])
        yield self.init_agents()
        self.log('Setup finished, starting the testcase.')

    def tearDown(self):
        self.messaging.disconnect()
        return self.process.terminate()
