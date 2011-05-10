from twisted.internet import defer
from twisted.python import failure

from feat.common import time
from feat.common.text_helper import format_block

from feat.test.integration import common
from feat.agents.base import agent, descriptor, replay, alert
from feat.agents.alert import alert_agent


@descriptor.register('alert_test_agent')
class Descriptor(descriptor.Descriptor):
    pass


@agent.register('alert_test_agent')
class Agent(agent.BaseAgent, alert.AgentMixin):

    @replay.entry_point
    def initiate(self, state):
        agent.BaseAgent.initiate(self)
        alert.AgentMixin.initiate(self, state)


@common.attr(timescale=0.1)
@common.attr('slow')
class AlertAgentTest(common.SimulationTest):

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        agency = spawn_agency()

        d1 = descriptor_factory('alert_test_agent')
        d2 = descriptor_factory('alert_agent')

        m1 = agency.start_agent(d1)
        m2 = agency.start_agent(d2)

        agent1 = m1.get_agent()
        agent2 = m2.get_agent()
        """)
        yield self.process(setup)
        yield self.wait_for_idle(10)

    def testValidateProlog(self):
        self.assertEqual(1, self.count_agents('alert_test_agent'))
        self.assertEqual(1, self.count_agents('alert_agent'))

    @defer.inlineCallbacks
    def testMappingBroadcastWithNotification(self):

        agent1 = self.get_local("agent1")
        agent2 = self.get_local("agent2")

        yield agent1.raise_alert("alert_text1", alert.Severity.medium)
        yield self.wait_for_idle(10)
        yield agent1.raise_alert("alert_text2", alert.Severity.low)
        yield self.wait_for_idle(10)
        yield agent1.raise_alert("alert_text1", alert.Severity.high)
        yield self.wait_for_idle(10)


        self.assertEqual(2, len(agent2.get_alerts()))
        self.assertEqual(alert.Severity.high, agent2.get_alert("alert_text1"))

        yield agent1.resolve_alert("alert_text1", alert.Severity.high)
        yield self.wait_for_idle(10)

        self.assertEqual(1, len(agent2.get_alerts()))
        self.assertEqual(None, agent2.get_alert("alert_text1"))
