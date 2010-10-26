# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from twisted.trial import unittest
from twisted.internet import defer, reactor
from twisted.python import log

from feat.agencies.emu import messaging
from zope.interface import implements
from feat.interfaces import agent

import uuid

class TestQueue(unittest.TestCase):

    def _appendConsumers(self, finished):
        defers = map(lambda _: self.queue.consume(
                                    ).addCallback(self._rcvCallback), range(5))
        defer.DeferredList(defers).addCallback(finished.callback)

    def _enqueueMsgs(self):
        for x in range(5):
            self.queue.enqueue("Msg %d" % x)

    def _assert5Msgs(self, _):
        log.msg('Received: %r' % self.received)
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
            d = self.queue.consume().addCallback(self._rcvCallback)
            defers.append(d)
            self.queue.enqueue("Msg %d" % x)

        d = defer.DeferredList(defers).addCallback(self._assert5Msgs)

        return d

    def testQueueWithoutConsumersKeepsMsgs(self):
        received = []

        self._enqueueMsgs()

        d = defer.Deferred()
        reactor.callLater(0.1, self._appendConsumers, d)

        d.addCallback(self._assert5Msgs)

        return d

    def testAppendConsumersThanSendMsgs(self):
        d  = defer.Deferred()
        self._appendConsumers(d)

        self._enqueueMsgs()

        d.addCallback(self._assert5Msgs)
        return d


class TestExchange(unittest.TestCase):

    def setUp(self):
        self.exchange = messaging.Exchange(name='test')
        self.queues = map(lambda x: messaging.Queue(name='queue %d' % x), \
                              range(3))

    def testQueueBindingAndUnbinding(self):
        for queue in self.queues:
            self.exchange.bind(queue.name, queue)

        self.assertEqual(3, len(self.exchange._bindings.keys()))
        for key in self.exchange._bindings:
            self.assertTrue(isinstance(self.exchange._bindings[key], list))
            self.assertEqual(1, len(self.exchange._bindings[key]))

        self.exchange.bind('queue 1', self.queues[0])
        self.assertEqual(2, len(self.exchange._bindings['queue 1']))
        self.exchange.unbind('queue 1', self.queues[0])

        for queue in self.queues:
            self.exchange.unbind(queue.name, queue)

        self.assertEqual(0, len(self.exchange._bindings))

    def testPublishingSameKey(self):
        routing_key = 'some key'
        for queue in self.queues:
            self.exchange.bind(routing_key, queue)

        for x in range(5):
            self.exchange.publish('Msg %d' % x, routing_key)

        for queue in self.queues:
            self.assertEqual(5, len(queue._messages))
            expected = ['Msg 0', 'Msg 1', 'Msg 2', 'Msg 3', 'Msg 4']
            self.assertEqual(expected, queue._messages)


    def testPublishingOneQueueBound(self):
        routing_key = 'some key'
        queue = self.queues[0]
        self.exchange.bind(routing_key, queue)

        for x in range(5):
            self.exchange.publish('Msg %d' % x, routing_key)

        self.assertEqual(5, len(queue._messages))
        expected = ['Msg 0', 'Msg 1', 'Msg 2', 'Msg 3', 'Msg 4']
        self.assertEqual(expected, queue._messages)

        self.assertEqual(0, len(self.queues[1]._messages))
        self.assertEqual(0, len(self.queues[2]._messages))


class StubAgent(object):
    implements(agent.IAgentMessaging)
    
    def __init__(self, shard_id=None):
        self._uuid = uuid.uuid1().get_hex()
        self._shard_id = shard_id or uuid.uuid1().get_hex()
        self.messages = []

    def getId(self):
        return self._uuid
    
    def onMessage(self, msg):
        self.messages.append(msg)

    def getShardId(self):
        return self._shard_id
        

class TestMessaging(unittest.TestCase):
    
    def setUp(self):
        self.messaging = messaging.Messaging()
        self.agent = StubAgent()
        self.connection = self.messaging.createConnection(self.agent)

    def testCreateConnection(self):
        self.assertTrue(isinstance(self.connection, messaging.Connection))
        self.assertEqual(1, len(self.messaging._queues))

        self.connection.disconnect()

    def test1To1Interest(self):
        key = self.agent.getId()
        interest = self.connection.createInterest1to1(key)
        self.assertEqual(1, len(self.connection.interests))

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

        def revoke_interest(_):
            interest.revoke()
            self.assertEqual(0, len(self.connection.interests))

        d.addCallback(revoke_interest)
        
        return d

