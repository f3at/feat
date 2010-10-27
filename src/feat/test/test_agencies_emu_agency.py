# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from feat.agencies.emu import agency
from twisted.trial import unittest
from feat.agents import agent, descriptor


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
