# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from feat.agencies.emu import agency
from twisted.trial import unittest
from feat.agents import agent, descriptor, requester
from feat.interface import recipient
from zope.interface import classProvides
from feat.interface.requester import IRequesterFactory
from twisted.python import log

import uuid


class DummyRequest(requester.BaseRequester):
    classProvides(IRequesterFactory)

    def __init__(self, agent, medium, argument):
        requester.BaseRequester.__init__(self, agent, medium, argument)
        self.payload = argument

    def initiate(self):
        msg = requester.BaseRequester.initiate(self)
        msg.payload = self.payload
        self.medium.request(msg)

    def on_respond(self, message):
        print message
        self.medium.terminate()


def callbackOnMessage(agency, shard, key):
    m = agency._messaging
    queue = m.defineQueue(name=uuid.uuid1())
    exchange = m._getExchange(shard)
    exchange.bind(key, queue)
    return queue.consume()


class TestAgencyAgent(unittest.TestCase):

    def setUp(self):
        self.agency = agency.Agency()
        desc = descriptor.Descriptor()
        self.agent = self.agency.start_agent(agent.BaseAgent, desc)

    def testJoinShard(self):
        self.assertEqual(1, len(self.agency._shards))
        self.assertEqual('lobby', self.agency._shards.keys()[0])
        self.assertEqual(1, len(self.agency._shards['lobby']))

        self.agent.leaveShard()
        self.assertEqual(1, len(self.agency._shards))
        self.assertEqual(0, len(self.agency._shards['lobby']))

    def testSendsMessage(self):
        recipients = recipient.Agent('some_agent', 'lobby')
        d = callbackOnMessage(self.agency, 'lobby', 'some_agent')
        self.agent.initiate_protocol(DummyRequest, recipients, 5)
        
        def asserts(message):
            log.msg(message)

        d.addCallback(asserts)

        return d
