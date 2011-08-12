# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import uuid

from twisted.internet import defer, reactor
from zope.interface import implements

from feat.agencies.emu import messaging
from feat.agents.base import descriptor, message, recipient
from feat.interface import agent

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
        self.queue = messaging.Queue(name="test")
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


class TestExchange(common.TestCase):

    def setUp(self):
        self.exchange = messaging.Exchange(name='test')
        self.queues = map(lambda x: messaging.Queue(name='queue %d' % x), \
                              range(3))

    def testQueueBindingAndUnbinding(self):
        for queue in self.queues:
            self.exchange._bind(queue.name, queue)

        self.assertEqual(3, len(self.exchange._bindings.keys()))
        for key in self.exchange._bindings:
            self.assertTrue(isinstance(self.exchange._bindings[key], list))
            self.assertEqual(1, len(self.exchange._bindings[key]))

        self.exchange._bind('queue 1', self.queues[0])
        self.assertEqual(2, len(self.exchange._bindings['queue 1']))
        self.exchange._unbind('queue 1', self.queues[0])

        for queue in self.queues:
            self.exchange._unbind(queue.name, queue)

        self.assertEqual(0, len(self.exchange._bindings))

    def testNotDoublingBindings(self):
        queue = self.queues[0]
        self.exchange._bind(queue.name, queue)
        self.assertEqual(1, len(self.exchange._bindings[queue.name]))

        self.exchange._bind(queue.name, queue)
        self.assertEqual(1, len(self.exchange._bindings[queue.name]))

    def testPublishingSameKey(self):
        routing_key = 'some key'
        for queue in self.queues:
            self.exchange._bind(routing_key, queue)

        for x in range(5):
            self.exchange.publish('Msg %d' % x, routing_key)

        for queue in self.queues:
            self.assertEqual(5, len(queue._messages))
            expected = ['Msg 0', 'Msg 1', 'Msg 2', 'Msg 3', 'Msg 4']
            self.assertEqual(expected, queue._messages)

    def testPublishingOneQueueBound(self):
        routing_key = 'some key'
        queue = self.queues[0]
        self.exchange._bind(routing_key, queue)

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
        self.messaging = messaging.Messaging()
        self.agent = common.StubAgent()
        self.connection = yield self.messaging.new_channel(self.agent)

    def testCreateConnection(self):
        self.assertTrue(isinstance(self.connection, messaging.Connection))
        self.assertEqual(1, len(self.messaging._queues))

        self.connection.release()

    def test1To1Binding(self):
        key = self.agent.channel_id
        binding = self.connection.bind(key)
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
    def testTwoAgentsWithSameBinding(self):
        agent2 = common.StubAgent()
        second_connection = yield self.messaging.new_channel(agent2)
        agents = [self.agent, agent2]
        connections = [self.connection, second_connection]

        key = 'some key'
        bindings = map(lambda x: x.bind(key), connections)

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

        yield d

    def testPublishingByAgent(self):
        key = self.agent.channel_id
        msg = message.BaseMessage(payload='some message')
        self.connection.bind(key, 'lobby')
        recip = recipient.Recipient(key, 'lobby')
        self.connection.post(recip, msg)
        d = defer.Deferred()

        def asserts(d):
            self.assertEqual(1, len(self.agent.messages))
            self.assertEqual('some message', self.agent.messages[0].payload)
            d.callback(None)

        reactor.callLater(0.1, asserts, d)

        return d
