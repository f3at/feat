# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from feat.agents.base import resource, testsuite, recipient, message
from feat.agents.shard import shard_agent
from feat.common.fiber import TriggerType


class TestShardAgent(testsuite.TestCase):

    def setUp(self):
        testsuite.TestCase.setUp(self)
        instance = self.ball.generate_agent(shard_agent.ShardAgent)
        instance.state.resources = self.ball.generate_resources(instance)
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
        # TODO: correct when the partnership protocol is ready
        # self.ball.descriptor.hosts = [
        #     recipient.Agent('agent1', shard),
        #     recipient.Agent('agent2', shard)]
        # self.ball.descriptor.children = [
        #     recipient.Agent('children', 'other shard')]
        self.ball.descriptor.allocations = [
            resource.Allocation(hosts=1, allocated=True),
            resource.Allocation(hosts=1, allocated=True),
            resource.Allocation(children=1, allocated=True)]

        interest = self.ball.generate_interest()
        sfx = [
            testsuite.side_effect('AgencyAgent.get_descriptor',
                                 self.ball.descriptor),
            testsuite.side_effect('AgencyAgent.get_descriptor',
                                 self.ball.descriptor),
            testsuite.side_effect('AgencyAgent.register_interest',
                                 result=interest,
                                 args=(shard_agent.JoinShardContractor, ))]
        result, state = self.ball.call(sfx, self.agent.initiate)
        alloc = state.resources.allocated()
        self.assertEqual(2, alloc.get('hosts', None))
        self.assertEqual(1, alloc.get('children', None))

    def testAddAgent(self):
        sfx = [
            testsuite.side_effect('AgencyAgent.get_descriptor',
                                  self.ball.descriptor)]
        f, state = self.ball.call(sfx, self.agent.add_agent,
                                  'joining_agent_id')
        expected_recipient = testsuite.CompareObject(
            recipient.Agent, shard=self.ball.descriptor.shard,
            key='joining_agent_id')
        self.assertFiberTriggered(f, TriggerType.succeed, self.ball.descriptor)
        self.assertFiberCalls(f, state.medium.update_descriptor)
        self.assertEqual(1, len(self.ball.descriptor.hosts))
        self.assertEqual(expected_recipient, self.ball.descriptor.hosts[0])

    def testAddChild(self):
        child = recipient.Agent('some agent', 'some shard')
        sfx = [
            testsuite.side_effect('AgencyAgent.get_descriptor',
                                  self.ball.descriptor)]
        f, state = self.ball.call(sfx, self.agent.add_children_shard, child)

        self.assertFiberTriggered(f, TriggerType.succeed, self.ball.descriptor)
        self.assertFiberCalls(f, state.medium.update_descriptor)
        self.assertEqual(1, len(self.ball.descriptor.children))
        self.assertEqual(child, self.ball.descriptor.children[0])


class TestJoinShardContractor(testsuite.TestCase):

    def setUp(self):
        testsuite.TestCase.setUp(self)
        agent = self.ball.generate_agent(shard_agent.ShardAgent)
        agent.state.resources = self.ball.generate_resources(agent)
        self.instance = self.ball.generate_contractor(
            agent, shard_agent.JoinShardContractor)

    def testAnnounceWithPlaceForHosts(self):
        self._load_contractor()
        s = self.agent._get_state()
        self.ball.call(None, s.resources.define, 'hosts', 1)
        self.ball.call(None, s.resources.define, 'children', 1)
        sfx = [
            testsuite.side_effect(
                resource.Resources._setup_allocation_expiration,
                args=testsuite.whatever)]
        announce = self._generate_announcement()

        f, state = self.ball.call(sfx, self.contractor.announced, announce)
        self.assertFiberTriggered(f, TriggerType.succeed)
        self.assertFiberDoesntCall(f, self.contractor._fetch_children_bids)

        expected_bid = testsuite.message(
            payload=dict(action_type=shard_agent.ActionType.join,
                         cost=0))
        self.assertFiberCalls(f, self.contractor._pick_best_bid,
                              args=(expected_bid, ))

    def testAnnounceWithoutPlaceForHosts(self):
        self._load_contractor()
        s = self.agent._get_state()
        self.ball.call(None, s.resources.define, 'hosts', 0)
        self.ball.call(None, s.resources.define, 'children', 1)
        sfx = [
            testsuite.side_effect(
                resource.Resources._setup_allocation_expiration,
                args=testsuite.whatever)]
        announce = self._generate_announcement()
        f, state = self.ball.call(sfx, self.contractor.announced, announce)
        self.assertFiberTriggered(f, TriggerType.succeed)
        self.assertFiberCalls(f, self.contractor._fetch_children_bids)

        expected_bid = testsuite.message(
            payload=dict(action_type=shard_agent.ActionType.create,
                         cost=20))
        self.assertFiberCalls(f, self.contractor._pick_best_bid,
                              args=(expected_bid, ))

    def testFetchChildrenBids(self):
        self._load_contractor()
        announce = self._generate_announcement()
        expected_announce = testsuite.message(
            payload=dict(level=1,
                         joining_agent=announce.payload['joining_agent']))

        shard = self.ball.descriptor.shard
        self.ball.descriptor.children = [
            recipient.Agent('child-id', 'other shard')]

        nested_manager = self.ball.generate_manager(
            self.agent, shard_agent.NestedJoinShardManager)
        sfx = [
            testsuite.side_effect('AgencyAgent.get_descriptor',
                                  self.ball.descriptor),
            testsuite.side_effect('AgencyAgent.initiate_protocol',
                                  result=nested_manager,
                                  args=(shard_agent.NestedJoinShardManager,
                                        self.ball.descriptor.children,
                                        expected_announce))]
        f, state = self.ball.call(sfx, self.contractor._fetch_children_bids,
                                  announce)
        self.assertEqual(nested_manager, state.nested_manager)
        self.assertFiberTriggered(f, TriggerType.succeed)
        self.assertFiberCalls(f, nested_manager.wait_for_bids)

    def testPickBestBid(self):
        self.instance.state.nested_manager = self.ball.generate_manager(
            self.instance.state.agent, shard_agent.NestedJoinShardManager)
        self._load_contractor()

        # scenario when own bid is cheaper
        nested_bids = [
            self._generate_bid(10),
            self._generate_bid(20)]
        own_bid = self._generate_bid(0)

        sfx = [
            testsuite.side_effect('AgencyManager.reject',
                                  args=(nested_bids[0], )),
            testsuite.side_effect('AgencyManager.reject',
                                  args=(nested_bids[1], ))]
        result, _ = self.ball.call(sfx, self.contractor._pick_best_bid,
                                   nested_bids, own_bid)
        self.assertEqual(own_bid, result)

        # scenario when nested_bid is cheaper
        nested_bids = [
            self._generate_bid(10),
            self._generate_bid(20)]
        own_bid = self._generate_bid(40)

        sfx = [
            testsuite.side_effect('AgencyManager.reject',
                                  args=(nested_bids[1], ))]
        result, _ = self.ball.call(sfx, self.contractor._pick_best_bid,
                                   nested_bids, own_bid)
        self.assertEqual(nested_bids[0], result)

    def testBidRefuseOrHandover(self):
        self._load_contractor()
        self._generate_preallocation()

        own_bid = self._generate_bid(0)
        other_bid = self._generate_bid(10)

        # sending refusal
        sfx = [testsuite.side_effect(
            'AgencyContractor.refuse', args=(testsuite.message(), ))]
        self.ball.call(sfx, self.contractor._bid_refuse_or_handover)

        # biding own
        sfx = [testsuite.side_effect(
            'AgencyContractor.bid', args=(own_bid, ))]
        self.ball.call(sfx, self.contractor._bid_refuse_or_handover,
                       own_bid, own_bid)

        # handing over
        sfx = [
            testsuite.side_effect(resource.Allocation.cancel_expiration_call),
            testsuite.side_effect(
            'AgencyContractor.handover', args=(other_bid, ))]
        _, s = self.ball.call(sfx, self.contractor._bid_refuse_or_handover,
                              other_bid, own_bid)
        self.assertEqual(resource.AllocationState.released,
                         s.preallocation.state)

    def testGranted(self):
        self._load_contractor()
        self._generate_preallocation()

        grant = message.Grant(payload=dict(
            joining_agent=recipient.Agent('some id', 'lobby')))
        bid = self._generate_bid(0)
        bid.payload['action_type'] = shard_agent.ActionType.join
        self.contractor._get_state().bid = bid
        sfx = [
            testsuite.side_effect(resource.Allocation.cancel_expiration_call)]
        f, s = self.ball.call(sfx, self.contractor.granted, grant)
        self.assertFiberTriggered(f, TriggerType.succeed, 'some id')
        self.assertFiberCalls(f, self.agent.add_agent)
        self.assertFiberCalls(f, self.contractor._finalize)
        self.assertEqual(resource.AllocationState.allocated,
                         s.preallocation.state)

    def testGrantedNewShard(self):
        self._load_contractor()
        self._generate_preallocation()

        grant = message.Grant(payload=dict(
            joining_agent=recipient.Agent('some id', 'lobby')))
        bid = self._generate_bid(0)
        bid.payload['action_type'] = shard_agent.ActionType.create
        self.contractor._get_state().bid = bid
        sfx = [
            testsuite.side_effect(resource.Allocation.cancel_expiration_call)]
        f, s = self.ball.call(sfx, self.contractor.granted, grant)
        self.assertFiberTriggered(f, TriggerType.succeed, 'some id')
        self.assertFiberDoesntCall(f, self.agent.add_agent)
        self.assertFiberCalls(f, self.agent.prepare_child_descriptor)
        self.assertFiberCalls(f, self.contractor._request_start_agent)
        self.assertFiberCalls(f, self.agent.add_children_shard)
        self.assertFiberCalls(f, self.contractor._finalize)
        self.assertEqual(resource.AllocationState.allocated,
                         s.preallocation.state)

    def _generate_preallocation(self):
        s = self.agent._get_state()
        self.ball.call(None, s.resources.define, 'hosts', 1)
        state = self.contractor._get_state()
        sfx = [
            testsuite.side_effect(
                resource.Resources._setup_allocation_expiration,
                args=testsuite.whatever)]
        result, _ = self.ball.call(
            sfx, self.agent.preallocate_resource, hosts=1)
        self.assertIsInstance(result, resource.Allocation)
        state.preallocation = result

    def _generate_bid(self, cost):
        return message.Bid(payload=dict(cost=cost))

    def _generate_announcement(self):
        announce = message.Announcement()
        announce.payload['level'] = 0
        announce.payload['joining_agent'] = recipient.Agent(
                'some host', 'lobby')
        return announce

    def _load_contractor(self):
        self.contractor = self.ball.load(self.instance)
        self.agent = self.contractor._get_state().agent
