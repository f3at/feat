# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from feat.test import common
from feat.agents.base import resource, testsuite, recipient
from feat.agents.shard import shard_agent


class TestShardAgent(testsuite.TestCase):

    def setUp(self):
        testsuite.TestCase.setUp(self)
        instance = self.ball.generate_agent(shard_agent.ShardAgent)
        instance.state.resource = self.ball.generate_resources(instance)
        self.agent = self.ball.load(instance)

    def testInitiateEmptyDescriptor(self):
        #host per shard
        hps = 10
        #children shards
        cs = 2

        interest = self.ball.generate_interest()
        sfx = [
            testsuite.side_effect('AgencyAgent.get_descriptor',
                                 self.ball.descriptor),
            testsuite.side_effect('AgencyAgent.register_interest',
                                 result=interest,
                                 args=(shard_agent.JoinShardContractor, )),
            testsuite.side_effect('Interest.bind_to_lobby')]
        result, state = self.ball.call(sfx, self.agent.initiate)
        alloc = state.resources.allocated()
        self.assertEqual(0, alloc.get('hosts', None))
        self.assertEqual(0, alloc.get('children', None))
        totals = state.resources.get_totals()
        self.assertEqual(hps, totals.get('hosts', None))
        self.assertEqual(cs, totals.get('children', None))

    def testInitiateWithChildrenInDescriptor(self):
        '''
        Check that information about children and members is recovered.
        Also check that if we have a parent we will not get bound to lobby.
        '''
        shard = self.ball.descriptor.shard
        self.ball.descriptor.parent = recipient.Agent('parent', 'root')
        self.ball.descriptor.hosts = [
            recipient.Agent('agent1', shard),
            recipient.Agent('agent2', shard)]
        self.ball.descriptor.children = [
            recipient.Agent('children', 'other shard')]

        interest = self.ball.generate_interest()
        sfx = [
            testsuite.side_effect('AgencyAgent.get_descriptor',
                                 self.ball.descriptor),
            testsuite.side_effect(resource.Allocation.initiate),
            testsuite.side_effect(resource.Allocation.initiate),
            testsuite.side_effect(resource.Allocation.initiate),
            testsuite.side_effect('AgencyAgent.register_interest',
                                 result=interest,
                                 args=(shard_agent.JoinShardContractor, ))]
        result, state = self.ball.call(sfx, self.agent.initiate)
        alloc = state.resources.allocated()
        self.assertEqual(2, alloc.get('hosts', None))
        self.assertEqual(1, alloc.get('children', None))
