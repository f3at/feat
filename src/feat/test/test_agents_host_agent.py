from feat.agents.base import testsuite, recipient, message, replier
from feat.agents.host import host_agent, port_allocator
from feat.agents.common import rpc
from feat.common import fiber
from feat.test import factories
from feat.agents.common.shard import JoinShardManager
from feat.test.common import attr, TestCase


class TestHostAgent(testsuite.TestCase):

    def setUp(self):
        testsuite.TestCase.setUp(self)
        instance = self.ball.generate_agent(host_agent.HostAgent)
        instance.state.resources = self.ball.generate_resources(instance)
        instance.state.partners = self.ball.generate_partners(instance)
        self.agent = self.ball.load(instance)

    def testInitiate(self):
        recp = recipient.Agent('join-shard', 'lobby')
        manager = self.ball.generate_manager(
            self.agent, JoinShardManager)
        expected = [
            testsuite.side_effect('AgencyAgent.get_descriptor',
                                 self.ball.descriptor),
            testsuite.side_effect('AgencyAgent.register_interest',
                                  args=(replier.GoodBye, )),
            testsuite.side_effect('AgencyAgent.register_interest',
                                  args=(replier.ProposalReceiver, )),
            testsuite.side_effect('AgencyAgent.register_interest',
                                  args=(rpc.RPCReplier, )),
            testsuite.side_effect('AgencyAgent.register_interest',
                                  args=(host_agent.StartAgentReplier, )),
            testsuite.side_effect('AgencyAgent.register_interest',
                            args=(host_agent.ResourcesAllocationContractor, )),
            testsuite.side_effect('AgencyAgent.get_descriptor',
                                 self.ball.descriptor), ]

        f, state = self.ball.call(expected, self.agent.initiate)
        self.assertFiberTriggered(f, fiber.TriggerType.succeed)
        self.assertFiberCalls(f, self.agent._update_hostname)
        self.assertFiberCalls(f, self.agent.initiate_partners)
#        self.assertFiberCalls(f, self.agent.start_join_shard_manager)


class TestPortAllocator(TestCase):

    def setUp(self):
        TestCase.setUp(self)
        ports = (5000, 5010)
        self.allocator = port_allocator.PortAllocator(self, ports)

    def testAllocate(self):
        ports = self.allocator.reserve_ports(5)
        self.assertEqual(len(ports), 5)
        self.assertEqual(self.allocator.num_free(), 5)
        self.assertEqual(self.allocator.num_used(), 5)

    def testAllocateAndRelease(self):
        ports = self.allocator.reserve_ports(5)
        self.allocator.release_ports(ports[2:])
        self.assertEqual(self.allocator.num_free(), 8)

    def testAllocateTooManyPorts(self):
        self.assertRaises(port_allocator.PortAllocationError,
                          self.allocator.reserve_ports, 11)

    def testReleaseUnknownPort(self):
        self.allocator.release_ports([15000])
        self.assertEqual(self.allocator.num_free(), 10)

    def testReleaseUnallocatedPort(self):
        self.allocator.release_ports([5000])
        self.assertEqual(self.allocator.num_free(), 10)

    def testSetPortsUsed(self):
        self.allocator.set_ports_used([5000, 5001])
        self.assertEqual(self.allocator.num_used(), 2)

    def testSetPortAlreadyUsed(self):
        ports = self.allocator.reserve_ports(5)
        self.allocator.set_ports_used(ports)
        self.assertEqual(self.allocator.num_used(), 5)

    def testSetUnknownPort(self):
        self.allocator.set_ports_used([15000, 15001])
        self.assertEqual(self.allocator.num_used(), 0)


@attr(skip="wip on transforming tree to a graph")
class TestJoinShardManager(testsuite.TestCase):

    def setUp(self):
        testsuite.TestCase.setUp(self)
        agent = self.ball.generate_agent(host_agent.HostAgent)
        instance = self.ball.generate_manager(agent, JoinShardManager)
        self.manager = self.ball.load(instance)

    def testInitiate(self):
        address = recipient.Agent(agent_id=self.ball.descriptor.doc_id,
                                  shard=self.ball.descriptor.shard)
        args = (
            testsuite.message(payload=dict(level=0, joining_agent=address,
                                           solutions="action")), )
        expected = [
            testsuite.side_effect('AgencyAgent.get_descriptor',
                                  self.ball.descriptor),
            testsuite.side_effect('AgencyManager.announce', args=args)]

        output, state = self.ball.call(expected, self.manager.initiate,
                                       "action")
#
#        output, state = self.ball.call(expected, self.manager.initiate,
#                                       "action")

    def testClosed(self):
        bids = [
            message.Bid(payload=dict(idd="best", cost=1)),
            message.Bid(payload=dict(idd="worse", cost=10))]
        sfx = [
            testsuite.side_effect('AgencyManager.get_bids', bids),
            testsuite.side_effect('AgencyAgent.get_descriptor',
                                  self.ball.descriptor),
            testsuite.side_effect('AgencyManager.grant',
                                  args=((bids[0], testsuite.whatever, ), ))]
        self.ball.call(sfx, self.manager.closed)
