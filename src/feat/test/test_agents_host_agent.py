from feat.agents.base import testsuite, recipient, message, replier
from feat.agents.host import host_agent
from feat.agents.common import rpc
from feat.common import fiber
from feat.test import factories
from feat.agents.common.shard import JoinShardManager
from feat.test.common import attr


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
                            args=(host_agent.ResourcesAllocationContractor, ))]

        f, state = self.ball.call(expected, self.agent.initiate)
        self.assertFiberTriggered(f, fiber.TriggerType.succeed)
        self.assertFiberCalls(f, self.agent._update_hostname)
        self.assertFiberCalls(f, self.agent.initiate_partners)
#        self.assertFiberCalls(f, self.agent.start_join_shard_manager)


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
