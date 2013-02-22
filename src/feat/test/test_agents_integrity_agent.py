
from feat.agents.integrity import integrity_agent, api
from feat.common import defer
from feat.database import conflicts
from feat.test import common, dummies
from feat.test.integration.common import ModelTestMixin


class DummyConnection(object):
    pass


class Method(object):

    def __init__(self, result=None):
        self.reset(result)

    def __call__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.called = True
        return self.result

    def reset(self, result=None):
        self.args = None
        self.kwargs = None
        self.called = False
        self.result = result


class IntegrationAgentTest(common.TestCase, ModelTestMixin):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        self.medium = dummies.DummyMedium(self)
        self.agent = integrity_agent.IntegrityAgent(self.medium)
        self.patch(conflicts, 'configure_replicator_database',
                   Method(defer.succeed(DummyConnection)))
        yield self.agent.initiate_agent()
        self.assertTrue(conflicts.configure_replicator_database.called)

        self.state = self.agent._get_state()

    @defer.inlineCallbacks
    def testSolveConflictAlerts(self):
        solve = Method()
        self.patch(conflicts, 'solve', solve)

        solve.reset(defer.succeed('id'))
        yield self.agent.conflict_cb('id', 'rev', False, False)
        self.assertTrue(solve.called)
        # this should not resolve alert, this would make nagios blow up
        self.assertNotIn('conflict-id', self.state.alert_statuses)

        # now fail solving conflict
        r = defer.fail(conflicts.UnsolvableConflict('bum', {'_id': 'id'}))
        solve.reset(r)
        yield self.agent.conflict_cb('id', 'rev', False, False)
        self.assertTrue(solve.called)
        # this should raise the alert
        self.assertIn('conflict-id', self.state.alert_statuses)
        self.assertEqual(1, self.state.alert_statuses['conflict-id'][0])

        solve.reset(defer.succeed('id'))
        yield self.agent.conflict_cb('id', 'rev', False, False)
        self.assertTrue(solve.called)
        # this should resolve alert
        self.assertIn('conflict-id', self.state.alert_statuses)
        self.assertEqual(0, self.state.alert_statuses['conflict-id'][0])
