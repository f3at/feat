from feat.test import common, dummies

from feat.common import defer
from feat.agencies import message
from feat.agents.base import alert, replay

from feat.interface.alert import Severity


class Alert1(alert.BaseAlert):
    name = 'service1'


class Alert2(alert.BaseAlert):
    name = 'service2'


class DummyAgent(replay.Replayable, alert.AgentMixin):

    alert.may_raise(Alert1)
    alert.may_raise(Alert2)

    def init_state(self, state, medium):
        state.medium = medium

    def get_agent_id(self):
        return 'agent1'

    def get_hostname(self):
        return 'test.feat.lan'

    def get_shard_id(self):
        return 'shard'

    def initiate_protocol(self, factory, *args, **kwargs):
        assert factory is alert.AlertPoster, repr(factory)
        poster = dummies.DummyPosterMedium()
        return factory(self, poster)


class TestCase(common.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        self.medium = dummies.DummyMedium(self)
        self.agent = DummyAgent(self.medium)
        self.medium.agent = self.agent
        yield self.agent.initiate()
        self.poster = self.agent._get_state().alerter._get_state().medium
        self.statuses = self.agent._get_state().alert_statuses

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
        self.assertEquals((1, 'it hurts!', Severity.warn),
                          self.statuses['service1'])

        self.agent.resolve_alert('service1', 'now better')
        self.assertEqual(2, len(self.poster.messages))
        m = self.poster.messages[-1]
        action, al = m.payload
        self.assertEqual('resolved', action)
        self.assertIsInstance(al, Alert1)
        self.assertEqual('test.feat.lan', al.hostname)
        self.assertEqual('now better', al.status_info)
        self.assertEqual('agent1', al.agent_id)
        self.assertEqual(alert.Severity.ok, al.severity)
        self.assertEqual('service1', al.name)
        self.assertEquals((0, 'now better', Severity.ok),
                          self.statuses['service1'])


class TestContractor(common.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        self.medium = dummies.DummyMedium(self)
        self.agent = DummyAgent(self.medium)
        self.medium.agent = self.agent
        self.state = self.agent._get_state()
        self.state.alert_factories = dict()
        self.state.alert_statuses = dict(service1=(1, "bum"))
        self.contractor_medium = dummies.DummyContractorMedium()
        self.contractor = alert.AlertsDiscoveryContractor(
            self.agent, self.contractor_medium)

    @defer.inlineCallbacks
    def testDiscovery(self):
        self.agent.may_raise_alert(Alert1)
        self.agent.may_raise_alert(Alert2)

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
        self.assertIn("service1", b.payload.statuses)
        self.assertEqual((1, "bum"), b.payload.statuses["service1"])
