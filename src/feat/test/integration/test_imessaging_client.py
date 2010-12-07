# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import shutil
import uuid
import os

from zope.interface import implements
from twisted.internet import reactor, defer
from twisted.trial.unittest import SkipTest

from feat.test.common import attr, delay
from feat.interface import agent
from feat.agencies.emu import messaging as emu_messaging
from feat.agents import descriptor


try:
    from feat.agencies.net import messaging
except ImportError as e:
    messaging = None
    import_error = e

from . import common


class TestCase(object):

    number_of_agents = 2

    def _agent(self, n):
        return dict(key=self.agents[n].descriptor.doc_id,
                    shard=self.agents[n].descriptor.shard)

    def init_agents(self):
        self.agents = [StubAgent() for x in range(self.number_of_agents)]
        self.connections = list()
        bindings = list()
        for agent in self.agents:
            connection = self.messaging.get_connection(agent)
            self.connections.append(connection)
            pb = connection.personal_binding(agent.descriptor.doc_id)
            bindings.append(pb)
        return defer.DeferredList(map(lambda b: b.created, bindings))

    @attr(number_of_agents=2)
    @defer.inlineCallbacks
    def testTwoAgentsTalking(self):
        d = self.cb_after(None, self.agents[1], 'on_message')
        d2 = self.cb_after(None, self.agents[0], 'on_message')
        self.connections[0].publish(message="you stupid!", **self._agent(1))
        yield d
        self.assertEqual(1, len(self.agents[1].messages))
        self.assertEqual('you stupid!', self.agents[1].messages[0])

        self.connections[0].publish(message="buzz off", **self._agent(0))

        yield d2
        self.assertEqual(1, len(self.agents[0].messages))
        self.assertEqual('buzz off', self.agents[0].messages[0])

    @defer.inlineCallbacks
    def testMultipleAgentsWithSameBinding(self):
        key = 'some key'
        bindings = map(lambda x: x.personal_binding(key), self.connections)
        yield defer.DeferredList(map(lambda x: x.created, bindings))

        self.connections[0].publish(message='some message',
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
        msg = "only for connection 0"

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
        msg = "only for connection 0"

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
        yield self.connections[1].publish(message="first message",
                                          **self._agent(0))
        yield d1
        yield self.disconnect_client()

        d2 = self.cb_after(None, self.agents[0], "on_message")
        yield self.connections[1].publish(message="second message",
                                          **self._agent(0))
        yield d2

        self.assertEqual(2, len(self.agents[0].messages))
        self.assertEqual("first message", self.agents[0].messages[0])
        self.assertEqual("second message", self.agents[0].messages[1])

    @attr(number_of_agents=3, timeout=20,
          skip="occasionally fails probably because of nontransactional mode")
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
                d = conn.publish(message=msg, **self._agent(target))
                deferrs.append(d)
            return defer.DeferredList(deferrs)

        def asserts(attempt):
            for agent in self.agents:
                self.assertEqual(attempt, len(agent.messages))
                self.assertTrue(agent.messages[-1].startswith("%s," % attempt))

        number_of_reconnections = 5

        yield self.rabbitmqctl_dump('list_bindings exchange_name queue_name')

        for index in range(1, number_of_reconnections + 1):
            d = wait_for_msgs()
            yield send_to_neighbour(index)

            self.log('Reconnecting %d time out of %d.',
                     index, number_of_reconnections)

            yield self.disconnect_client()
            yield self.rabbitmqctl_dump('list_queues name messages '
                                        'messages_ready consumers')

            yield d
            yield self.rabbitmqctl_dump('list_queues name messages')
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
        connection = self.messaging.get_connection(agent)

        # wait for connection to be established
        client = yield connection._messaging.factory.add_connection_made_cb()

        self.assertIsInstance(client, messaging.MessagingClient)
        binding = connection.personal_binding(agent.descriptor.doc_id)
        yield binding.created

        d = self.cb_after(None, agent, 'on_message')
        connection.publish(message='something', **self._agent(0))
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

    def configure(self):
        self.config = dict()
        self.config['port'] = self.get_free_port()
        self.config['mnesia_dir'] = '/tmp/rabbitmq-rabbit-mnesia'

    def prepare_workspace(self):
        shutil.rmtree(self.config['mnesia_dir'], ignore_errors=True)

    @defer.inlineCallbacks
    def setUp(self):
        if messaging is None:
            raise SkipTest('Skipping the test because of missing '
                           'dependecies: %r' % import_error)

        rabbitmq = '/usr/lib/rabbitmq/bin/rabbitmq-server'
        start_script = os.path.normpath(os.path.join(
            os.path.dirname(__file__), '..', '..', '..', '..',
            'tools', 'start_rabbit.sh'))
        self.check_installed(rabbitmq)
        self.check_installed(start_script)

        self.configure()
        self.prepare_workspace()

        self.control = common.ControlProtocol(self, self._started_test)
        self.process = reactor.spawnProcess(
            self.control, start_script, args=[start_script], env={
                'HOME': os.environ['HOME'],
                'RABBITMQ_NODE_PORT': str(self.config['port']),
                'RABBITMQ_MNESIA_DIR': self.config['mnesia_dir']})

        yield self.control.ready

        self.messaging = messaging.Messaging('127.0.0.1', self.config['port'])
        yield self.init_agents()
        self.log('Setup finished, starting the testcase.')

    def rabbitmqctl(self, command):
        rabbitmq = '/usr/lib/rabbitmq/bin/rabbitmqctl'
        start_script = os.path.normpath(os.path.join(
            os.path.dirname(__file__), '..', '..', '..', '..',
            'tools', 'start_rabbitctl.sh'))
        self.check_installed(rabbitmq)
        self.check_installed(start_script)

        args = [start_script] + command.split()

        control = common.RunProtocol(self)
        reactor.spawnProcess(
            control, start_script, args=args, env={
                'HOME': os.environ['HOME'],
                'RABBITMQ_NODE_PORT': str(self.config['port']),
                'RABBITMQ_MNESIA_DIR': self.config['mnesia_dir']})
        return control.finished

    def rabbitmqctl_dump(self, command):
        d = self.rabbitmqctl(command)
        d.addCallback(lambda output:
                      self.log("Output of command 'rabbitmqctl %s':\n%s\n",
                               command, output))
        return d

    def _started_test(self, buffer):
        self.log("Checking buffer: %s", buffer)
        return "broker running" in buffer

    def tearDown(self):
        self.messaging.disconnect()
        self.process.signalProcess("TERM")
        return self.control.exited


class StubAgent(object):
    implements(agent.IAgencyAgent)

    def __init__(self):
        self.descriptor = descriptor.Descriptor(shard='lobby',
                                                _id=str(uuid.uuid1()))
        self.messages = []

    def on_message(self, msg):
        self.messages.append(msg)

    def get_id(self):
        return self.descriptor.doc_id
