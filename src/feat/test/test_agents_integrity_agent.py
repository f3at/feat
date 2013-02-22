
from feat.agents.integrity import integrity_agent, api
from feat.common import defer
from feat.database import conflicts, emu
from feat.test import common, dummies
from feat.test.integration.common import ModelTestMixin

from feat.models.interface import InvalidParameters


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


class _Base(common.TestCase, ModelTestMixin):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        self.medium = dummies.DummyMedium(self)
        self.agent = integrity_agent.IntegrityAgent(self.medium)

        self.connection = emu.Database().get_connection()
        self.patch(conflicts, 'configure_replicator_database',
                   Method(defer.succeed(self.connection)))
        yield self.agent.initiate_agent()
        self.assertTrue(conflicts.configure_replicator_database.called)

        self.state = self.agent._get_state()


class IntegrationAgentTest(_Base):

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


class ApiTest(_Base):

    @defer.inlineCallbacks
    def setUp(self):
        yield _Base.setUp(self)

        self.model = api.IntegrityAgent(self.agent)
        yield self.model.initiate()

    @defer.inlineCallbacks
    def testCreateReplicationSuccessful(self):
        get_replication_status = Method()
        self.patch(conflicts, 'get_replication_status', get_replication_status)
        get_replication_status.reset(defer.succeed({}))
        submodel = yield self.model_descend(self.model, 'replications')

        yield submodel.perform_action('post', target='target')
        view = yield self.connection.query_view(conflicts.Replications,
                                                key=('source', 'test'),
                                                include_docs=True)
        self.assertEqual(1, len(view))
        repl = view[0]
        self.assertIsInstance(repl, dict)
        self.assertEqual(True, repl.get('continuous'))
        self.assertEqual('target', repl.get('target'))
        self.assertEqual('test', repl.get('source'))
        self.assertEqual('featjs/replication', repl.get('filter'))

    @defer.inlineCallbacks
    def testCreateReplicationAlreadyExist(self):
        get_replication_status = Method()
        self.patch(conflicts, 'get_replication_status', get_replication_status)
        result = {'target': [(10, True, 'triggered', 'id2')]}
        get_replication_status.reset(defer.succeed(result))
        submodel = yield self.model_descend(self.model, 'replications')

        d = submodel.perform_action('post', target='target')
        self.assertFailure(d, InvalidParameters)
        # assert no doc is created
        view = yield self.connection.query_view(conflicts.Replications,
                                                key=('source', 'test'),
                                                include_docs=True)
        self.assertEqual(0, len(view))

    @defer.inlineCallbacks
    def testGetReplications(self):
        get_replication_status = Method()
        self.patch(conflicts, 'get_replication_status', get_replication_status)

        result = {
            'target1': [(4, True, 'completed', 'id1'),
                        (10, True, 'triggered', 'id2')],
            'target2': [(0, False, 'error', 'id3')]}
        get_replication_status.reset(defer.succeed(result))
        submodel = yield self.model_descend(self.model, 'replications')

        js = yield self.model_as_json(submodel)

        exp = {
            'target1': {'last_seq': 10,
                        'continuous': True,
                        'status': 'triggered',
                        'id': 'id2'},
            'target2': {'last_seq': 0,
                        'continuous': False,
                        'status': 'error',
                        'id': 'id3'}}

        self.assertEqual(exp, js)
