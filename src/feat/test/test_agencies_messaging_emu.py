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
from twisted.internet import reactor

from feat.agencies.messaging import emu
from feat.agencies import message, recipient
from feat.common import defer

from . import common


class TestQueue(common.TestCase):

    def _appendConsumers(self, finished):
        defers = map(lambda _: self.queue.get(
                                    ).addCallback(self._rcvCallback), range(5))
        defer.DeferredList(defers).addCallback(finished.callback)

    def _enqueueMsgs(self):
        for x in range(5):
            self.queue.enqueue("Msg %d" % x)

    def _assert5Msgs(self, _):
        self.log('Received: %r' % self.received)
        for x in range(5):
            self.assertTrue(len(self.received) > 0)
            self.assertEqual("Msg %d" % x, self.received.pop(0))

    def _rcvCallback(self, msg):
        self.received.append(msg)

    def setUp(self):
        self.queue = emu.Queue(name="test")
        self.received = []

    def testQueueConsumers(self):
        defers = []

        for x in range(5):
            d = self.queue.get().addCallback(self._rcvCallback)
            defers.append(d)
            self.queue.enqueue("Msg %d" % x)

        d = defer.DeferredList(defers).addCallback(self._assert5Msgs)

        return d

    def testQueueWithoutConsumersKeepsMsgs(self):
        self._enqueueMsgs()

        d = defer.Deferred()
        reactor.callLater(0.1, self._appendConsumers, d)

        d.addCallback(self._assert5Msgs)

        return d

    def testAppendConsumersThanSendMsgs(self):
        d = defer.Deferred()
        self._appendConsumers(d)

        self._enqueueMsgs()

        d.addCallback(self._assert5Msgs)
        return d


class TestFanoutExchange(common.TestCase):

    def setUp(self):
        self.exchange = emu.FanoutExchange(name='test')
        self.queues = map(lambda x: emu.Queue(name='queue %d' % x), \
                              range(3))

    def testQueueBindingAndUnbinding(self):
        for queue in self.queues:
            self.exchange.bind(queue)

        self.assertEqual(3, len(self.exchange._bindings))
        for binding in self.exchange._bindings:
            self.assertIsInstance(binding, emu.Queue)

        self.exchange.bind(self.queues[0])
        self.assertEqual(3, len(self.exchange._bindings))

        for queue in self.queues:
            self.exchange.unbind(queue)

        self.assertEqual(0, len(self.exchange._bindings))

    def testPublishing(self):
        for queue in self.queues:
            self.exchange.bind(queue)

        for x in range(5):
            self.exchange.publish('Msg %d' % x)

        for queue in self.queues:
            self.assertEqual(5, len(queue._messages))
            expected = ['Msg 0', 'Msg 1', 'Msg 2', 'Msg 3', 'Msg 4']
            self.assertEqual(expected, queue._messages)


class TestDirectExchange(common.TestCase):

    def setUp(self):
        self.exchange = emu.DirectExchange(name='test')
        self.queues = map(lambda x: emu.Queue(name='queue %d' % x), \
                              range(3))

    def testQueueBindingAndUnbinding(self):
        for queue in self.queues:
            self.exchange.bind(queue, queue.name)

        self.assertEqual(3, len(self.exchange._bindings.keys()))
        for key in self.exchange._bindings:
            self.assertTrue(isinstance(self.exchange._bindings[key], list))
            self.assertEqual(1, len(self.exchange._bindings[key]))

        self.exchange.bind(self.queues[0], 'queue 1')
        self.assertEqual(2, len(self.exchange._bindings['queue 1']))
        self.exchange.unbind(self.queues[0], 'queue 1')

        for queue in self.queues:
            self.exchange.unbind(queue, queue.name)

        self.assertEqual(0, len(self.exchange._bindings))

    def testNotDoublingBindings(self):
        queue = self.queues[0]
        self.exchange.bind(queue, queue.name)
        self.assertEqual(1, len(self.exchange._bindings[queue.name]))

        self.exchange.bind(queue, queue.name)
        self.assertEqual(1, len(self.exchange._bindings[queue.name]))

    def testPublishingSameKey(self):
        routing_key = 'some key'
        for queue in self.queues:
            self.exchange.bind(queue, routing_key)

        for x in range(5):
            self.exchange.publish('Msg %d' % x, routing_key)

        for queue in self.queues:
            self.assertEqual(5, len(queue._messages))
            expected = ['Msg 0', 'Msg 1', 'Msg 2', 'Msg 3', 'Msg 4']
            self.assertEqual(expected, queue._messages)

    def testPublishingOneQueueBound(self):
        routing_key = 'some key'
        queue = self.queues[0]
        self.exchange.bind(queue, routing_key)

        for x in range(5):
            self.exchange.publish('Msg %d' % x, routing_key)

        self.assertEqual(5, len(queue._messages))
        expected = ['Msg 0', 'Msg 1', 'Msg 2', 'Msg 3', 'Msg 4']
        self.assertEqual(expected, queue._messages)

        self.assertEqual(0, len(self.queues[1]._messages))
        self.assertEqual(0, len(self.queues[2]._messages))


class TestMessaging(common.TestCase):

    timeout = 1

    @defer.inlineCallbacks
    def setUp(self):
        self.messaging = emu.RabbitMQ()
        self.agent = common.StubAgent()
        self.connection = self.messaging.new_channel(
            self.agent, self.agent.get_agent_id())
        yield self.connection.initiate()

    def testCreateConnection(self):
        self.assertTrue(isinstance(self.connection, emu.Connection))
        self.assertEqual(1, len(self.messaging._queues))

        self.connection.release()

    def test1To1Binding(self):
        key = self.agent.get_agent_id()
        route = self.agent.get_shard_id()
        binding = self.connection.bind(route, key)
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

    @defer.inlineCallbacks
    def testBindingToFanoutExchange(self):
        route = self.agent.get_shard_id()
        binding = self.connection.bind(route)
        self.assertEqual(1, len(self.connection.get_bindings()))

        exchange = self.messaging._exchanges.values()[0]
        self.assertIsInstance(exchange, emu.FanoutExchange)

        exchange.publish('Message')

        def check():
            return len(self.agent.messages) == 1

        yield self.wait_for(check, 1, 0.01)
        self.assertEqual(['Message'], self.agent.messages)

    @defer.inlineCallbacks
    def testTwoAgentsWithSameBinding(self):
        agent2 = common.StubAgent()
        second_connection = self.messaging.new_channel(
            agent2, agent2.get_agent_id())
        yield second_connection.initiate()
        agents = [self.agent, agent2]
        connections = [self.connection, second_connection]

        key = 'some key'
        route = self.agent.get_shard_id()
        bindings = map(lambda x: x.bind(route, key), connections)

        self.assertEqual(1, len(self.messaging._exchanges))
        exchange = self.messaging._exchanges.values()[0]
        exchange.publish('some message', key)

        yield common.delay(None, 0.1)

        for agent in agents:
            self.assertEqual(1, len(agent.messages))

        map(lambda x: x.revoke(), bindings)
        self.assertEqual(0, len(self.connection.get_bindings()))

    def testPublishingByAgent(self):
        key = self.agent.get_agent_id()
        msg = message.BaseMessage(payload='some message')
        self.connection.bind('lobby', key)
        recip = recipient.Recipient(key, 'lobby')
        self.connection.post(recip, msg)
        d = defer.Deferred()

        def asserts(d):
            self.assertEqual(1, len(self.agent.messages))
            self.assertEqual('some message', self.agent.messages[0].payload)
            d.callback(None)

        reactor.callLater(0.1, asserts, d)

        return d
