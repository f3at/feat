# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4


from feat.agencies.emu import agency
from twisted.trial import unittest
from feat.agents import agent, descriptor, requester
from feat.interface import recipient
from zope.interface import classProvides
from feat.interface.requester import IRequesterFactory
from feat.common import log

import uuid
import common


class DummyRequest(requester.BaseRequester):
    classProvides(IRequesterFactory)

    def __init__(self, agent, medium, argument):
        requester.BaseRequester.__init__(self, agent, medium, argument)
        self.payload = argument

    def initiate(self):
        msg = requester.BaseRequester.initiate(self)
        msg.payload = self.payload
        self.medium.request(msg)

    def got_reply(self, message):
        print message
        self.medium.terminate()


class TestAgencyAgent(unittest.TestCase):

    timeout = 3

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
        d = self.agency.callbackOnMessage('lobby', 'some_agent')
        payload = 5
        self.agent.initiate_protocol(DummyRequest, recipients, payload)
        
        def asserts(message):
            self.assertEqual(self.agent.descriptor.shard, \
                             message.reply_to_shard)
            self.assertEqual(self.agent.descriptor.key, \
                             message.reply_to_key)
            self.assertEqual('Request', message.protocol_type)
            self.assertEqual('DummyRequest', message.protocol_id)
            self.assertEqual(payload. message.payload)

            session_id = message.session_id

        d.addCallback(asserts)

        return d

#    testSendsMessage.skip = "To be done mańana"        
