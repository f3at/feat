import urlparse

from twisted.internet import task as itask

from feat.agents.application import feat
from feat.agents.base import agent, descriptor, replay, task, alert
from feat.common import error, fiber, defer
from feat.database import conflicts

from feat.database.interface import IDocument


@feat.register_descriptor("integrity_agent")
class Descriptor(descriptor.Descriptor):
    pass


ALERT_NAME = 'couchdb-conflicts'


REPLICATION_PROGRESS_ALERT_THRESHOLD = 0.99


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
                             c.host, c.port, c.username, c.password)
        f.add_callback(self._replicator_configured)
        return f

    def startup(self):
        self.initiate_protocol(task.LoopingCall, 60, #once a minute
                               self.cleanup_logs)
        db = self.get_database()
        db.changes_listener(conflicts.Conflicts, self.conflict_cb)

        # The change listener is not always informing us the new
        # incoming conflicts. If the conflicting revision is a
        # loosing one, no conflict will be emitted. To remedy this
        # we query for conflicts one every 5 minutes.
        self.initiate_protocol(task.LoopingCall, 300, self.query_conflicts)

        # One of the responsibilities of this agent is to warn us
        # if replication to configured databases fails for any reason.
        # It checks it once every 5 minutes.
        self.initiate_protocol(task.LoopingCall, 300,
                               self.check_configured_replications)

    def shutdown(self):
        self._clear_connections()

    def on_killed(self):
        self._clear_connections()

    ### checking status of configured replications ###

    @replay.immutable
    @defer.inlineCallbacks
    def check_configured_replications(self, state):
        self.debug("checking status of configured replications")
        statuses = yield conflicts.get_replication_status(
            state.replicator, state.db_config.name)
        if not statuses:
            self.debug("No replications configured")
            return
        db = self.get_database()
        our_seq = yield db.get_update_seq()

        for target, rows in statuses.iteritems():
            alert_name = self.get_replication_alert_name(target)
            self.may_raise_alert(
                alert.DynamicAlert(
                    name=alert_name,
                    severity=alert.Severity.warn,
                    persistent=True,
                    description='replication-' + alert_name))

            update_seq, continuous, status, replication_id = rows[0]
            progress = float(update_seq) / our_seq
            if progress >= REPLICATION_PROGRESS_ALERT_THRESHOLD:
                self.debug("Replication to %s is fine.", target)
                self.resolve_alert(alert_name, 'ok')
            else:
                if status == 'completed':
                    info = ('The replication is paused, '
                            'last progress: %2.0f %%.'
                            % (progress * 100, ))
                    severity = alert.Severity.warn
                elif status == 'task_missing':
                    info = (
                        'The continuous replication is triggered '
                        'but there is no active task running for it. '
                        'The only time I saw this case was due to the '
                        'bug in couchdb, which required restarting it. '
                        'Please investigate!')
                    severity = alert.Severity.critical
                elif status == 'running':
                    info = (
                        "The replication is running, but hasn't yet reached "
                        "the desired threshold of: %2.0f %%. "
                        "Current progress is: %2.0f %%"
                        % (REPLICATION_PROGRESS_ALERT_THRESHOLD * 100,
                           progress * 100))
                    severity = alert.Severity.warn
                else:
                    info = 'The replication is in %s state.' % (
                        status, )
                    severity = alert.Severity.critical

                self.info("Replication to %s is not fine. Rasing alert: %s",
                          target, info)
                self.raise_alert(alert_name, info, severity)

    def get_replication_alert_name(self, target):
        '''
        Generate a name out replication target extracted from
        couchdb.
        '''
        parsed = urlparse.urlparse(target)
        netloc = parsed.netloc
        if '@' in netloc:
            netloc = netloc.split('@', 1)[1]
        return netloc + parsed.path

    ### cleanup of logs ###

    @replay.immutable
    def cleanup_logs(self, state):
        self.debug("Running cleanup update logs.")
        d = conflicts.cleanup_logs(self.get_database(), state.replicator)
        d.addCallback(defer.inject_param, 1, self.debug,
                      "Cleaned up %d update logs.")
        d.addErrback(defer.inject_param, 1, error.handle_failure,
                     self, "cleanup_logs() call failed")
        return d

    ### solving conflicts ###

    @replay.immutable
    def query_conflicts(self, state):
        db = state.medium.get_database()
        d = db.query_view(conflicts.Conflicts, parse_results=False)
        d.addCallback(self.update_unsolvable_conflicts)
        d.addCallback(self.handle_conflicts)
        return d

    @replay.mutable
    def update_unsolvable_conflicts(self, state, rows):
        ids = set([x[2] for x in rows])
        # The conflict might have been solved by different instance or
        # by intervention from human. Here we notice this so that the
        # alert is eventually resolved.
        for x in state.unsolvable_conflicts - ids:
            state.unsolvable_conflicts.remove(x)
        return ids

    def handle_conflicts(self, ids):
        self.info("Detected %d conflicts", len(ids))
        if ids:
            return itask.coiterate(
                (self.conflict_cb(doc_id) for doc_id in ids))
        else:
            self.resolve_alert(ALERT_NAME, 'ok')

    @replay.immutable
    def conflict_cb(self, state, doc_id, rev=None, deleted=False,
            own_change=False):
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
            self.raise_alert(ALERT_NAME,
                             '%d documents are in conflict' %
                             (len(state.unsolvable_conflicts, )))
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
