# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import uuid
import time

from twisted.internet import reactor
from twisted.trial.unittest import SkipTest

from feat.test.common import attr, delay, StubAgent, Mock
from feat.common import defer
from feat.agencies.messaging import emu
from feat.agencies import message, recipient
from feat.process import rabbitmq
from feat.process.base import DependencyError


try:
    from feat.agencies.messaging import net
except ImportError as e:
    messaging = None
    import_error = e

from feat.test.integration import common


def m(payload):
    '''
    Wraps the payload into BaseMessage.
    '''
    m_id = str(uuid.uuid1())
    return message.BaseMessage(payload=payload, message_id=m_id,
                               expiration_time=time.time() + 5)


def unwrap(msg):
    '''
    Perform the reverse operation to m().
    '''
    assert isinstance(msg, message.BaseMessage)
    return msg.payload


class TestCase(object):

    number_of_agents = 2

    def _agent(self, n):
        agent_id = self.agents[n].get_agent_id()
        return recipient.Recipient(agent_id, 'lobby')

    @defer.inlineCallbacks
    def init_agents(self):
        self.agents = [StubAgent() for x in range(self.number_of_agents)]
        self.connections = list()
        bindings = list()
        for agent in self.agents:
            connection = self.messaging.new_channel(agent,
                                                    agent.get_agent_id())
            yield connection.initiate()
            self.connections.append(connection)
            pb = connection.bind('lobby', agent.get_agent_id())
            bindings.append(pb)
        yield defer.DeferredList(map(lambda b: b.wait_created(), bindings))

    @attr(number_of_agents=2)
    @defer.inlineCallbacks
    def testTwoAgentsTalking(self):
        d = self.cb_after(None, self.agents[1], 'on_message')
        d2 = self.cb_after(None, self.agents[0], 'on_message')
        self.connections[0].post(self._agent(1), m("you stupid!"))
        yield d
        self.assertEqual(1, len(self.agents[1].messages))
        self.assertEqual('you stupid!', unwrap(self.agents[1].messages[0]))

        self.connections[0].post(self._agent(0), m("buzz off"))

        yield d2
        self.assertEqual(1, len(self.agents[0].messages))
        self.assertEqual('buzz off', unwrap(self.agents[0].messages[0]))

    @defer.inlineCallbacks
    def testMultipleAgentsWithSameBinding(self):
        key = 'some key'
        bindings = map(lambda x: x.bind('lobby', key), self.connections)
        yield defer.DeferredList(map(lambda x: x.wait_created(), bindings))
        recip = recipient.Recipient(key, 'lobby')
        self.connections[0].post(recip, m('some message'))
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

        bindings = [self.connections[0].bind(shard, key),
                    self.connections[1].bind('lobby', key)]
        yield defer.DeferredList(map(lambda x: x.wait_created(), bindings))

        d = self.cb_after(None, obj=self.agents[0], method="on_message")
        recip = recipient.Recipient(key, shard)
        yield self.connections[1].post(recip, msg)
        yield d

        self.assertEqual(0, len(self.agents[1].messages))
        self.assertEqual(1, len(self.agents[0].messages))
        self.assertEqual(msg, self.agents[0].messages[0])

    @defer.inlineCallbacks
    def testRevokedBindingsDontBind(self):
        shard = 'some shard'
        key = 'some key'
        msg = m("only for connection 0")

        bindings = [self.connections[0].bind(shard, key),
                    self.connections[1].bind('lobby', key)]
        yield defer.DeferredList(map(lambda x: x.wait_created(), bindings))

        yield defer.DeferredList(map(lambda x: x.revoke(), bindings))

        recip = recipient.Recipient(key, shard)
        yield self.connections[1].post(recip, msg)

        yield delay(None, 0.1)

        for agent in self.agents:
            self.assertEqual(0, len(agent.messages))


class CallbacksReceiver(Mock):

    @Mock.stub
    def on_connect(self):
        pass

    @Mock.stub
    def on_disconnect(self):
        pass


class RabbitSpecific(object):
    """
    This testcase is specific for RabbitMQ integration, as simulation of
    disconnection doesn't make sense for the emu implementation.
    """

    def disconnect_client(self):
        return self.messaging._connector.disconnect()

    def setup_receiver(self):
        mock = CallbacksReceiver()
        self.messaging.add_disconnected_cb(mock.on_disconnect)
        self.messaging.add_reconnected_cb(mock.on_connect)
        return mock

    @attr(number_of_agents=10)
    @defer.inlineCallbacks
    def testReconnect(self):
        mock = self.setup_receiver()
        d1 = self.cb_after(None, self.agents[0], "on_message")
        yield self.connections[1].post(self._agent(0), m("first message"))
        yield d1
        yield self.disconnect_client()
        yield common.delay(None, 0.1)
        self.assertCalled(mock, 'on_disconnect', times=1)

        d2 = self.cb_after(None, self.agents[0], "on_message")
        yield self.connections[1].post(self._agent(0), m("second message"))
        yield d2

        self.assertEqual(2, len(self.agents[0].messages))
        self.assertEqual("first message", unwrap(self.agents[0].messages[0]))
        self.assertEqual("second message", unwrap(self.agents[0].messages[1]))
        self.assertCalled(mock, 'on_connect', times=1)

    @attr(number_of_agents=3, timeout=50)
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
                d = conn.post(self._agent(target), m(msg))
                deferrs.append(d)
            return defer.DeferredList(deferrs)

        def asserts(attempt):
            for agent in self.agents:
                self.assertEqual(attempt, len(agent.messages))
                self.assertTrue(
                    unwrap(agent.messages[-1]).startswith("%s," % attempt))

        number_of_reconnections = 5
        mock = self.setup_receiver()

        for index in range(1, number_of_reconnections + 1):
            d = wait_for_msgs()
            yield send_to_neighbour(index)

            self.log('Reconnecting %d time out of %d.',
                     index, number_of_reconnections)

            yield self.disconnect_client()
            yield common.delay(None, 0.1)
            self.assertCalled(mock, 'on_disconnect', times=index)
            self.assertCalled(mock, 'on_connect', times=index-1)

            yield d
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
        channel = self.messaging.new_channel(agent,
                                             agent.get_agent_id())
        yield channel.initiate()
        # wait for connection to be established
        client = yield channel._client.factory.add_connection_made_cb()

        self.assertIsInstance(client, net.MessagingClient)
        binding = channel.bind(agent.get_shard_id(), agent.get_agent_id())
        yield binding.wait_created()

        d = self.cb_after(None, agent, 'on_message')
        channel.post(self._agent(0), m('something'))
        yield d

        self.assertEqual(1, len(agent.messages))


class EmuMessagingIntegrationTest(common.IntegrationTest, TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.IntegrationTest.setUp(self)
        self.messaging = emu.RabbitMQ()
        yield self.init_agents()


@attr('slow')
class RabbitIntegrationTest(common.IntegrationTest, TestCase,
                            RabbitSpecific):

    timeout = 10

    configurable_attributes = ['number_of_agents']

    @defer.inlineCallbacks
    def setUp(self):
        yield common.IntegrationTest.setUp(self)
        if net is None:
            raise SkipTest('Skipping the test because of missing '
                           'dependecies: %r' % import_error)

        try:
            self.process = rabbitmq.Process(self)
        except DependencyError as e:
            raise SkipTest(str(e))

        yield self.process.restart()

        self.messaging = net.RabbitMQ(
            '127.0.0.1', self.process.get_config()['port'])
        yield self.messaging.connect()
        yield self.init_agents()
        self.log('Setup finished, starting the testcase.')

    def tearDown(self):
        self.messaging.disconnect()
        return self.process.terminate()


@attr('slow')
class ConnectionProblemsTest(common.IntegrationTest):
    """
    This test case connects to not existing rabbitmq first and than
    corrects it's error.
    """
    number_of_agents = 2

    @defer.inlineCallbacks
    def setUp(self):
        if net is None:
            raise SkipTest('Skipping the test because of missing '
                           'dependecies: %r' % import_error)

        try:
            self.process = rabbitmq.Process(self)
        except DependencyError as e:
            raise SkipTest(str(e))

        yield self.process.restart()

        port = self.process.get_config()['port']
        #noone is listening at this address
        self.messaging = net.RabbitMQ('127.0.0.1',
                                      port + 1, timeout=0.1)

        connect_d = self.messaging.connect()
        self.assertFailure(connect_d, defer.TimeoutError)

        yield connect_d

        self.info('Will reconfigure messaging in 2 seconds')
        reactor.callLater(5, self.messaging.reconfigure, '127.0.0.1', port)

        yield self.init_agents()

    def tearDown(self):
        self.messaging.disconnect()
        return self.process.terminate()

    # Copy only one test case and methods it depends from,
    # the point is too check that one test work.
    _agent = TestCase._agent.__func__
    init_agents = TestCase.init_agents.__func__
    testTwoAgentsTalking = TestCase.testTwoAgentsTalking.__func__
