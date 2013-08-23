from feat.agents.application import feat
from feat.agents.base import agent, descriptor, replay, task, alert
from feat.common import error, fiber, defer
from feat.database import conflicts

from feat.database.interface import IDocument


@feat.register_descriptor("integrity_agent")
class Descriptor(descriptor.Descriptor):
    pass


class CleanupLogsTask(task.StealthPeriodicTask):

    CLEANUP_FREQUENCY = 60 #once a minute

    @replay.mutable
    def initiate(self, state, connection):
        '''
        @param connection: IDatabaseConnection bound to _replicator database.
        '''
        state.connection = connection
        return fiber.wrap_defer(task.StealthPeriodicTask.initiate, self,
                                self.CLEANUP_FREQUENCY)

    @replay.immutable
    def run(self, state):
        self.debug("Running cleanup update logs.")
        d = conflicts.cleanup_logs(state.agent.get_database(),
                                   state.connection)
        d.addCallback(defer.inject_param, 1, self.debug,
                      "Cleaned up %d update logs.")
        d.addErrback(defer.inject_param, 1, error.handle_failure,
                     self, "cleanup_logs() call failed")
        return d


@feat.register_agent("integrity_agent")
class IntegrityAgent(agent.BaseAgent):

    @replay.mutable
    def initiate(self, state):
        state.db_config = c = state.medium.agency.get_config().db
        f = fiber.wrap_defer(conflicts.configure_replicator_database,
                             c.host, c.port)
        f.add_callback(self._replicator_configured)
        return f

    @replay.journaled
    def startup(self, state):
        self.initiate_protocol(CleanupLogsTask, state.replicator)
        db = state.medium.get_database()
        db.changes_listener(conflicts.Conflicts, self.conflict_cb)

        self.call_next(self.query_conflicts_on_startup)

    @replay.mutable
    def shutdown(self, state):
        self._clear_connections()

    @replay.mutable
    def on_killed(self, state):
        self._clear_connections()

    ### solving conflicts ###

    @replay.immutable
    def query_conflicts_on_startup(self, state):
        db = state.medium.get_database()
        d = db.query_view(conflicts.Conflicts, parse_results=False)
        d.addCallback(self.handle_conflicts_on_startup)
        return d

    def handle_conflicts_on_startup(self, rows):
        self.info("Detected %d conflicts on startup", len(rows))
        d = defer.succeed(None)
        for row in rows:
            d.addCallback(defer.drop_param, self.conflict_cb,
                          row[2], rev=None, deleted=False, own_change=False)
        return d

    @replay.immutable
    def conflict_cb(self, state, doc_id, rev, deleted, own_change):
        d = conflicts.solve(state.medium.get_database(), doc_id)
        d.addCallbacks(self._solve_cb, self._solve_err,
                       callbackArgs=(doc_id, ))
        return d

    @replay.immutable
    def _solve_cb(self, state, _ignored, doc_id):
        # resolve the alert only if we previously raised the alert
        # for this document
        name = self._alert_name(doc_id)
        if name in state.alert_factories:
            self.resolve_alert(name, 'solved')

    @replay.immutable
    def _solve_err(self, state, fail):
        fail.trap(conflicts.UnsolvableConflict)
        doc = fail.value.doc
        if IDocument.providedBy(doc):
            doc_id = doc.doc_id
        else:
            doc_id = doc['_id']
        name = self._alert_name(doc_id)
        self.may_raise_alert(alert.DynamicAlert(
            name=name,
            severity=alert.Severity.warn,
            description=name))
        self.raise_alert(name, error.get_failure_message(fail))

    def _alert_name(self, doc_id):
        return 'conflict-%s' % (doc_id, )

    ### private initialization ###

    @replay.mutable
    def _replicator_configured(self, state, connection):
        state.replicator = connection

    ### private shutdown and cleanup ###

    @replay.immutable
    def _clear_connections(self, state):
        if hasattr(state, 'replicator'):
            state.replicator.disconnect()
            state.replicator.database.disconnect()
