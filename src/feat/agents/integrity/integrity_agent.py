from feat.agents.application import feat
from feat.agents.base import agent, descriptor, replay, task, alert
from feat.common import error, fiber, defer
from feat.database import conflicts

from feat.database.interface import IDocument


@feat.register_descriptor("integrity_agent")
class Descriptor(descriptor.Descriptor):
    pass


class CheckConflicts(task.StealthPeriodicTask):

    CLEANUP_FREQUENCY = 300 #once every 5 minutes

    def initiate(self):
        return task.StealthPeriodicTask.initiate(
            self, self.CLEANUP_FREQUENCY)

    @replay.immutable
    def run(self, state):
        return state.query_conflicts()


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


ALERT_NAME = 'couchdb-conflicts'


@feat.register_agent("integrity_agent")
class IntegrityAgent(agent.BaseAgent):

    @replay.mutable
    def initiate(self, state):
        self.may_raise_alert(alert.DynamicAlert(
            name=ALERT_NAME,
            severity=alert.Severity.warn,
            description=ALERT_NAME))

        state.unsolvable_conflicts = set()

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

        # The change listener is not always informing us the new
        # incoming conflicts. If the conflicting revision is a
        # loosing one, no conflict will be emitted. To remedy this
        # we query for conflicts one every 5 minutes.
        self.initiate_protocol(CheckConflicts)

    @replay.mutable
    def shutdown(self, state):
        self._clear_connections()

    @replay.mutable
    def on_killed(self, state):
        self._clear_connections()

    ### solving conflicts ###

    @replay.immutable
    def query_conflicts(self, state):
        db = state.medium.get_database()
        d = db.query_view(conflicts.Conflicts, parse_results=False)
        d.addCallback(self.handle_conflicts)
        return d

    def handle_conflicts(self, rows):
        self.info("Detected %d conflicts", len(rows))
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
        try:
            state.unsolvable_conflicts.remove(doc_id)
        except KeyError:
            pass
        if state.unsolvable_conflicts:
            self.raise_alert(ALERT_NAME, ', '.join(state.unsolvable_conflicts))
        else:
            self.resolve_alert(ALERT_NAME, 'ok')

    @replay.immutable
    def _solve_err(self, state, fail):
        if fail.check(conflicts.UnsolvableConflict):
            doc = fail.value.doc
            if IDocument.providedBy(doc):
                doc_id = doc.doc_id
            else:
                doc_id = doc['_id']
                state.unsolvable_conflicts.add(doc_id)
            self.warning('Cannot solve conflict for document id: %s. '
                         'Reason: %s', doc_id, fail.value)

            self.raise_alert(ALERT_NAME, ', '.join(state.unsolvable_conflicts))
        else:
            error.handle_failure(self, fail, 'Failed solving conflict.')
            msg = error.get_failure_message(fail)
            self.raise_alert(ALERT_NAME, msg, severity=alert.Severity.critical)

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
