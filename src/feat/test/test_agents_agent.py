# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from feat.agencies.emu import agency
from twisted.trial import unittest
from feat.agents import agent

class TestBaseAgent(unittest.TestCase):

    def setUp(self):
        self.agency = agency.Agency()
        self.agent = agent.BaseAgent(agent.Descriptor())
        self.agency.registerAgent(self.agent)
        
    def testJoinedShard(self):
        self.assertEqual(1, len(self.agency._shards))
        self.assertEqual('lobby', self.agency._shards.keys()[0])
