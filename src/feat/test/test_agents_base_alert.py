from feat.test import common, dummies

from feat.common import defer
from feat.agencies import message
from feat.agents.base import alert, replay


class Alert1(alert.BaseAlert):
    name = 'service1'
    severity = alert.Severity.warn


class Alert2(alert.BaseAlert):
    name = 'service2'
    severity = alert.Severity.critical


class DummyAgent(replay.Replayable, alert.AgentMixin):

    alert.may_raise(Alert1)
    alert.may_raise(Alert2)

    def init_state(self, state, medium):
        state.medium = medium

    def get_agent_id(self):
        return 'agent1'

    def get_hostname(self):
        return 'test.feat.lan'


class TestCase(common.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        self.medium = dummies.DummyMedium(self)
        self.agent = DummyAgent(self.medium)
        self.medium.agent = self.agent
        self.state = self.agent._get_state()
        self.poster = dummies.DummyPosterMedium()
        self.state.alerter = alert.AlertPoster(
            self.agent, self.poster)

    def testRaisingAndAlert(self):
        self.agent.raise_alert('service1', 'it hurts!')
        self.assertEqual(1, len(self.poster.messages))
        m = self.poster.messages[-1]
        action, al = m.payload
        self.assertEqual('raised', action)
        self.assertIsInstance(al, Alert1)
        self.assertEqual('test.feat.lan', al.hostname)
        self.assertEqual('it hurts!', al.status_info)
        self.assertEqual('agent1', al.agent_id)
        self.assertEqual(alert.Severity.warn, al.severity)
        self.assertEqual('service1', al.name)

        self.agent.resolve_alert('service1', 'now better')
        self.assertEqual(2, len(self.poster.messages))
        m = self.poster.messages[-1]
        action, al = m.payload
        self.assertEqual('resolved', action)
        self.assertIsInstance(al, Alert1)
        self.assertEqual('test.feat.lan', al.hostname)
        self.assertEqual('now better', al.status_info)
        self.assertEqual('agent1', al.agent_id)
        self.assertEqual(alert.Severity.warn, al.severity)
        self.assertEqual('service1', al.name)


class TestContractor(common.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        self.medium = dummies.DummyMedium(self)
        self.agent = DummyAgent(self.medium)
        self.medium.agent = self.agent
        self.state = self.agent._get_state()
        self.contractor_medium = dummies.DummyContractorMedium()
        self.contractor = alert.AlertsDiscoveryContractor(
            self.agent, self.contractor_medium)

    @defer.inlineCallbacks
    def testDiscovery(self):
        self.agent._register_alert_factory(Alert1)
        self.agent._register_alert_factory(Alert2)

        announcement = message.Announcement()
        yield self.contractor.announced(announcement)
        b = self.contractor_medium.bid_sent
        self.assertIsInstance(b, message.Bid)
        self.assertIsInstance(b.payload, alert.AlertingAgentEntry)
        self.assertEqual('test.feat.lan', b.payload.hostname)
        self.assertEqual('agent1', b.payload.agent_id)
        self.assertEqual(2, len(b.payload.alerts))
        self.assertIn(Alert1, b.payload.alerts)
        self.assertIn(Alert2, b.payload.alerts)
