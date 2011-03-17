# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from feat.agents.base import resource, testsuite, recipient, message, replier
from feat.agents.shard import shard_agent
from feat.agents.common.shard import ActionType
from feat.common.fiber import TriggerType

from feat.agents.base.testsuite import AnySideEffect

from feat.test.common import attr


class TestShardAgent(testsuite.TestCase):

    def setUp(self):
        testsuite.TestCase.setUp(self)
        instance = self.ball.generate_agent(shard_agent.ShardAgent)
        instance.state.resources = self.ball.generate_resources(instance)
        instance.state.partners = self.ball.generate_partners(instance)
        self.agent = self.ball.load(instance)

    @attr(skip="wip on changing tree to a graph")
    def testInitiateEmptyDescriptor(self):
        #host per shard
        hps = 10
        #neighbour shards
        ns = 3

        interest = self.ball.generate_interest()
        sfx = [
            testsuite.side_effect('AgencyAgent.get_descriptor',
                                 self.ball.descriptor),
            testsuite.side_effect('AgencyAgent.register_interest',
                                  args=(replier.GoodBye, )),
            testsuite.side_effect('AgencyAgent.register_interest',
                                  args=(replier.ProposalReceiver, )),
            testsuite.side_effect('AgencyAgent.register_interest',
                                 result=interest,
                            args=(shard_agent.FindNeighboursContractor, )),
            testsuite.side_effect('Interest.bind_to_lobby'),
            testsuite.side_effect('AgencyAgent.get_descriptor',
                                 self.ball.descriptor)]
        result, state = self.ball.call(sfx, self.agent.initiate)
        alloc = state.resources.allocated()
        self.assertEqual(0, alloc.get('hosts', None))
        self.assertEqual(0, alloc.get('neighbours', None))
        totals = state.resources.get_totals()
        self.assertEqual(hps, totals.get('hosts', None))
        self.assertEqual(ns, totals.get('neighbours', None))

    @attr(skip="wip on changing tree to a graph")
    def testInitiateWithChildrenInDescriptor(self):
        '''
        Check that information about children and members is recovered.
        Also check that if we have a parent we will not get bound to lobby.
        '''
        a = [
            resource.Allocation(id=1, hosts=1, allocated=True),
            resource.Allocation(id=2, hosts=1, allocated=True),
            resource.Allocation(id=3, children=1, allocated=True)]
        self.ball.descriptor.allocations = a

        self.ball.descriptor.partners = [
            shard_agent.ParentShardPartner(recipient.dummy_agent()),
            shard_agent.HostPartner(recipient.dummy_agent(), a[0].id),
            shard_agent.HostPartner(recipient.dummy_agent(), a[1].id),
            shard_agent.ChildShardPartner(recipient.dummy_agent(), a[2].id)]

        interest = self.ball.generate_interest()
        sfx = [
            testsuite.side_effect('AgencyAgent.get_descriptor',
                                 self.ball.descriptor),
            testsuite.side_effect('AgencyAgent.register_interest',
                                  args=(replier.GoodBye, )),
            testsuite.side_effect('AgencyAgent.register_interest',
                                  args=(replier.ProposalReceiver, )),
            testsuite.side_effect('AgencyAgent.register_interest',
                                 result=interest,
                                 args=(shard_agent.JoinShardContractor, )),
            testsuite.side_effect('Interest.bind_to_lobby'),
            testsuite.side_effect('AgencyAgent.get_descriptor',
                                 self.ball.descriptor),
            testsuite.side_effect('Interest.unbind_from_lobby'),
            testsuite.side_effect('AgencyAgent.get_descriptor',
                                 self.ball.descriptor),
            testsuite.side_effect('AgencyAgent.get_descriptor',
                                 self.ball.descriptor)]
        result, state = self.ball.call(sfx, self.agent.initiate)
        alloc = state.resources.allocated()
        self.assertEqual(2, alloc.get('hosts', None))
        self.assertEqual(1, alloc.get('children', None))


@attr(skip="wip on changing graph to a tree")
class TestJoinShardContractor(testsuite.TestCase):

    def setUp(self):
        testsuite.TestCase.setUp(self)
        agent = self.ball.generate_agent(shard_agent.ShardAgent)
        agent.state.resources = self.ball.generate_resources(agent)
        agent.state.partners = self.ball.generate_partners(agent)
        self.instance = self.ball.generate_contractor(
            agent, shard_agent.JoinShardContractor)

    def testAnnounceWithPlaceForHosts(self):
        self._load_contractor()
        state = self.agent._get_state()
        call = self.ball.generate_call(state.resources.define)
        call('hosts', 1)
        call('children', 1)

        announce = self._generate_announcement()
        call = self.ball.generate_call(self.contractor.announced)
        alloc_exp = resource.Resources._setup_allocation_expiration
        call.add_side_effect(AnySideEffect(None, alloc_exp))
        result = call(announce)

        self.assertFiberTriggered(result, TriggerType.succeed)
        self.assertFiberDoesntCall(result,
                         self.contractor._fetch_children_bids)

        expected_bid = testsuite.message(
            payload=dict(action_type=ActionType.join, cost=0))
        self.assertFiberCalls(result, self.contractor._pick_best_bid,
                              args=(expected_bid, ))

    def testAnnounceWithoutPlaceForHosts(self):
        self._load_contractor()
        state = self.agent._get_state()
        call = self.ball.generate_call(state.resources.define)
        call('hosts', 0)
        call('children', 1)

        announce = self._generate_announcement()
        call = self.ball.generate_call(self.contractor.announced)
        alloc_exp = resource.Resources._setup_allocation_expiration
        call.add_side_effect(AnySideEffect(None, alloc_exp))
        result = call(announce)

        self.assertFiberTriggered(result, TriggerType.succeed)
        self.assertFiberCalls(result, self.contractor._fetch_children_bids)

        expected_bid = testsuite.message(
            payload=dict(action_type=ActionType.create, cost=20))
        self.assertFiberCalls(result, self.contractor._pick_best_bid,
                              args=(expected_bid, ))

    def testFetchChildrenBids(self):
        self._load_contractor()
        announce = self._generate_announcement()
        expected_announce = testsuite.message(
            payload=dict(level=1,
                         joining_agent=announce.payload['joining_agent'],
                         solutions=announce.payload['solutions']))

        self.ball.descriptor.partners = [
            shard_agent.ChildShardPartner(
                recipient.Agent('child-id', 'other shard'))]

        nested_manager = self.ball.generate_manager(
            self.agent, shard_agent.NestedJoinShardManager)

        sfx = [
            testsuite.side_effect('AgencyAgent.get_descriptor',
                                  self.ball.descriptor),
            testsuite.side_effect('AgencyAgent.initiate_protocol',
                                  result=nested_manager,
                                  args=(shard_agent.NestedJoinShardManager,
                                        self.ball.descriptor.partners,
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
        f, s = self.ball.call(None, self.contractor._bid_refuse_or_handover,
                              other_bid, own_bid)
        self.assertFiberCalls(f, self.contractor._get_state().medium.handover)
        self.assertFiberCalls(f, self.contractor.release_preallocation)

    def testGranted(self):
        self._load_contractor()
        self._generate_preallocation()

        grant = message.Grant(payload=dict(
            joining_agent=recipient.Agent('some id', 'lobby')))
        bid = self._generate_bid(0)
        bid.payload['action_type'] = ActionType.join
        self.contractor._get_state().bid = bid
        f, s = self.ball.call(None, self.contractor.granted, grant)
        self.assertFiberTriggered(f, TriggerType.succeed, testsuite.whatever)
        self.assertFiberCalls(f, self.contractor._finalize)
        self.assertFiberCalls(f, self.agent.confirm_allocation)

    def testGrantedNewShard(self):
        self._load_contractor()
        self._generate_preallocation()

        grant = message.Grant(payload=dict(
            joining_agent=recipient.Agent('some id', 'lobby')))
        bid = self._generate_bid(0)
        bid.payload['action_type'] = ActionType.create
        self.contractor._get_state().bid = bid
        f, s = self.ball.call(None, self.contractor.granted, grant)
        self.assertFiberTriggered(f, TriggerType.succeed, testsuite.whatever)
        self.assertFiberCalls(f, self.agent.prepare_child_descriptor)
        self.assertFiberCalls(f, self.contractor._request_start_agent)
        self.assertFiberCalls(f, self.contractor._finalize)
        self.assertFiberCalls(f, self.agent.confirm_allocation)

    def _generate_preallocation(self):
        agent_state = self.agent._get_state()
        call = self.ball.generate_call(agent_state.resources.define)
        call('hosts', 1)

        contractor_state = self.contractor._get_state()
        call = self.ball.generate_call(self.agent.preallocate_resource)
        fun = resource.Resources._setup_allocation_expiration
        call.add_side_effect(AnySideEffect(fun))
        result = call(hosts=1)
        self.assertIsInstance(result, resource.Allocation)
        contractor_state.preallocation_id = result.id

    def _generate_bid(self, cost):
        return message.Bid(payload=dict(cost=cost))

    def _generate_announcement(self):
        announce = message.Announcement()
        announce.payload['level'] = 0
        announce.payload['joining_agent'] = recipient.Agent(
                'some host', 'lobby')
        announce.payload['solutions'] = \
            (ActionType.create, ActionType.join, )
        return announce

    def _load_contractor(self):
        self.contractor = self.ball.load(self.instance)
        self.agent = self.contractor._get_state().agent
