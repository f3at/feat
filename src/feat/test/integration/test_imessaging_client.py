# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import shutil
import uuid
import os

from zope.interface import implements
from twisted.internet import reactor, defer
from twisted.trial.unittest import SkipTest
from feat.test.common import attr
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

    @attr(skip='transfrom in integration test')
    def test1To1Binding(self):
        key = self.agent.get_id()
        binding = self.connection.personal_binding(key)
        self.assertEqual(1, len(self.connection.get_bindings()))

        exchange = self.messaging._exchanges.values()[0]
        for x in range(5):
            exchange.publish('Msg %d' % x, key)

        d = defer.Deferred()

        def asserts(finished):
            self.assertEqual(5, len(self.agent.messages))
            expected = ['Msg 0', 'Msg 1', 'Msg 2', 'Msg 3', 'Msg 4']
            self.assertEqual(expected, self.agent.messages)
            finished.callback(None)
        reactor.callLater(0.1, asserts, d)

        def revoke_binding(_):
            binding.revoke()
            self.assertEqual(0, len(self.connection.get_bindings()))

        d.addCallback(revoke_binding)

        return d

    @attr(skip='transfrom in integration test')
    def testTwoAgentsWithSameBinding(self):
        second_agent = StubAgent()
        second_connection = self.messaging.get_connection(second_agent)
        agents = [self.agent, second_agent]
        connections = [self.connection, second_connection]

        key = 'some key'
        bindings = map(lambda x: x.personal_binding(key), connections)

        self.assertEqual(1, len(self.messaging._exchanges))
        exchange = self.messaging._exchanges.values()[0]
        exchange.publish('some message', key)

        d = defer.Deferred()

        def asserts(finished):
            for agent in agents:
                self.assertEqual(1, len(agent.messages))
            finished.callback(None)
        reactor.callLater(0.1, asserts, d)

        def revoke_bindings(_):
            map(lambda x: x.revoke(), bindings)
            self.assertEqual(0, len(self.connection.get_bindings()))

        d.addCallback(revoke_bindings)

        return d

    @attr(skip='transfrom in integration test')
    def testPublishingByAgent(self):
        key = self.agent.get_id()
        self.connection.personal_binding(key)
        self.connection.publish(key, self.agent.descriptor.shard,\
                                   'some message')
        d = defer.Deferred()

        def asserts(d):
            self.assertEqual(['some message'], self.agent.messages)
            d.callback(None)

        reactor.callLater(0.1, asserts, d)

        return d


class EmuMessagingIntegrationTest(common.IntegrationTest, TestCase):

    def setUp(self):
        self.messaging = emu_messaging.Messaging()
        return self.init_agents()


@attr('slow')
class RabbitIntegrationTest(common.IntegrationTest, TestCase):

    timeout = 3

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
