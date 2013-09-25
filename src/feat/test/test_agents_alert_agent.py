from feat.test import common, dummies
from feat.test.integration.common import ModelTestMixin

from feat.common import defer
from feat.agents.alert import alert_agent
from feat.agents.base import alert
from feat.gateway import models
from feat.models import response

from feat.interface.protocols import ProtocolFailed
from feat.interface.alert import Severity


class Alert1(alert.BaseAlert):
    name = 'service1'


class Alert2(alert.BaseAlert):
    name = 'service2'


class DummyMedium(dummies.DummyMedium):

    _protocols = dict()

    def get_configuration(self):
        return alert_agent.AlertAgentConfiguration()

    def get_base_gateway_url(self):
        return 'http://localhost/'


class TestAgent(common.TestCase, ModelTestMixin):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        self.medium = DummyMedium(self)
        self.agent = alert_agent.AlertAgent(self.medium)
        self.medium.agent = self.agent
        yield self.agent.initiate_agent()
        self.state = self.agent._get_state()
        self.state.config.hosts = ['host1', 'host2', 'host3']

    @defer.inlineCallbacks
    def testReceiveAlertsForUnknownService(self):
        a = Alert1(hostname='host1',
                   status_info='omg!',
                   agent_id='agent1')
        yield self.agent.alert_raised(a)

        self.assertEqual(1, len(self.state.alerts))

        S = Severity
        self._assert_service('host1', 'agent1', Alert1,
                             received=1, status_info='omg!',
                             severity=S.warn)
        self.assertEqual(1, len(self.medium.calls))
        self.assertEqual(self.agent.rescan_shard,
                         self.medium.calls.values()[0][1])

        a.status_info = 'fire!'
        a.severity = S.critical
        yield self.agent.alert_raised(a)
        self._assert_service('host1', 'agent1', Alert1,
                             received=2, status_info='fire!',
                             severity=S.critical)
        self.assertEqual(1, len(self.medium.calls))

        a.status_info = 'uff ok again'
        yield self.agent.alert_resolved(a)
        self._assert_service('host1', 'agent1', Alert1,
                             received=0, status_info='uff ok again',
                             severity=S.ok)
        self.assertEqual(1, len(self.medium.calls))

        # now validate the model for the current state
        model = models.AlertAgent(self.agent)
        yield model.initiate()
        yield self.validate_model_tree(model)

    @defer.inlineCallbacks
    def testScanningShard(self):
        self.medium.reset()
        model = models.AlertAgent(self.agent)
        d = model.perform_action('rescan')
        self.assertEqual(1, len(self.medium.protocols))

        S = Severity
        resp = [
            alert.AlertingAgentEntry(
                hostname='host1',
                agent_id='agent1',
                alerts=[Alert1, Alert2],
                statuses=dict(service1=(1, 'bum', S.warn))),
            alert.AlertingAgentEntry(
                hostname='host2',
                agent_id='agent2',
                alerts=[Alert1])]
        p = ProtocolFailed(resp)
        self.medium.protocols[0].deferred.errback(p)
        res = yield d
        self.assertIsInstance(res, response.Done)

        self.assertEqual(3, len(self.state.alerts),
                         str(self.state.alerts.keys()))

        self._assert_service('host1', 'agent1', Alert1, received=1,
                             status_info="bum", severity=S.warn)
        self._assert_service('host1', 'agent1', Alert2, severity=S.ok)
        self._assert_service('host2', 'agent2', Alert1, severity=S.ok)
        self.medium.reset()

        # now rescan and discover new services

        d = model.perform_action('rescan')
        self.assertEqual(1, len(self.medium.protocols))

        resp = [
            alert.AlertingAgentEntry(
                hostname='host1',
                agent_id='agent1',
                alerts=[Alert1, Alert2]),
            alert.AlertingAgentEntry(
                hostname='host3',
                agent_id='agent3',
                alerts=[Alert1, Alert2])]
        p = ProtocolFailed(resp)
        self.medium.protocols[0].deferred.errback(p)
        yield d

        self.assertEqual(4, len(self.state.alerts))
        self._assert_service('host1', 'agent1', Alert1, received=1,
                             status_info="bum", severity=S.warn)
        self._assert_service('host1', 'agent1', Alert2, severity=S.ok)
        self._assert_service('host3', 'agent3', Alert1, severity=S.ok)
        self._assert_service('host3', 'agent3', Alert2, severity=S.ok)

    def _assert_service(self, hostname, agent_id, alert,
                        received=0, status_info=None,
                        severity=None):
        key = (hostname, "-".join([agent_id, alert.name]))
        self.assertIn(key, self.state.alerts, self.state.alerts.keys())
        a = self.state.alerts[key]
        self.assertIsInstance(a, alert_agent.AlertService)
        self.assertEqual(received, a.received_count)
        self.assertEqual(alert.name, a.name)
        self.assertEqual(severity, a.severity)
        self.assertEqual(hostname, a.hostname)
        self.assertEqual(status_info, a.status_info)
        self.assertEqual(agent_id, a.agent_id)
