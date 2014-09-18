import operator

from twisted.python.failure import Failure
from twisted.internet import task as itask


from feat.agents.application import feat
from feat.common.text_helper import format_block
from feat.common import defer, error, first
from feat.database import view, driver, update

from feat.database.interface import NotFoundError, IDocument
from feat.database.interface import ConflictResolutionStrategy


class UnsolvableConflict(error.NonCritical):

    def __init__(self, msg, doc, *args, **kwargs):
        error.NonCritical.__init__(self, msg, *args, **kwargs)
        self.doc = doc

    log_level = 3
    log_line_template = "Failed solving conflict."


class Modified(Exception):
    pass


@feat.register_view
class Conflicts(view.JavascriptView):

    design_doc_id = 'featjs'
    name = 'conflicts'

    map = format_block('''
    function(doc) {
        if (doc._conflicts) {
            emit(doc._id, null);
        }
    }''')

    filter = format_block('''
    function(doc, request) {
        if (doc._conflicts) {
            return true;
        }
        return false;
    }''')


@feat.register_view
class Replication(view.JavascriptView):
    '''
    Replication filter to be used between feat database.
    The deletes of update logs are made local.
    The design documents are not transfered, because its a
    responsibility of feat-service upgrade command to
    maintain them.
    '''

    design_doc_id = 'featjs'
    name = 'replication'

    filter = format_block('''
    function(doc, request) {
        if (doc[".type"] == "update_log" && doc._deleted) {
            return false;
        }
        if (doc._id.indexOf("_design") === 0) {
            return false;
        }
        return true;
    }''')


@feat.register_view
class UpdateLogs(view.JavascriptView):

    design_doc_id = 'featjs'
    name = 'update_logs'

    map = format_block('''
    function(doc) {
        if (doc[".type"] == "update_log") {
            // querying for a specific document by merge logic
            emit(["doc_id", doc.owner_id], null);
            // querying by cleanup logic for local update logs
            emit(["seq_num", doc.partition_tag, doc.seq_num], doc.owner_id);
            // querying by cleanup logic for update logs imported from
            // different partinions
            emit(["rev", doc.partition_tag, doc.owner_id, doc.rev_to], null);
        }
    }''')

    @classmethod
    def until_seq(cls, partition_tag, seq):
        if seq is None:
            seq = {}
        return dict(startkey=("seq_num", partition_tag),
                    endkey=("seq_num", partition_tag, seq))

    @classmethod
    def all(cls):
        return dict(startkey=("rev", ), endkey=("rev", {}))

    @classmethod
    def for_doc(cls, doc_id):
        return dict(startkey=("doc_id", doc_id), endkey=("doc_id", doc_id, {}),
                    include_docs=True)


class Replications(view.JavascriptView):

    design_doc_id = 'featjs'
    name = 'replications'

    map = format_block('''
    function(doc) {
        if (doc._replication_id) {
            emit(["source", doc.source], null);
            emit(["target", doc.target], null);
        }
    }''')


@defer.inlineCallbacks
def configure_replicator_database(host, port, username=None, password=None):
    """
    Connects to dabatase, checks the version and creates the
    design document used by feat (if it doesn't exist).

    @returns: IDatabaseConnection bound to _replicator database
    """
    database = driver.Database(host, port, '_replicator', username, password)
    connection = database.get_connection()
    version = yield database.get_version()
    if version < (1, 1, 0):
        database.disconnect()
        raise ValueError("Found couchdb version %r. "
                         "_replicator database has been introduced in 1.1.0." %
                         (version, ))
    design_docs = view.DesignDocument.generate_from_views([Replications])
    for doc in design_docs:
        try:
            doc2 = yield connection.get_document(doc.doc_id)
            if doc.views != doc2.views or doc.filters != doc2.filters:
                doc.rev = doc2.rev
                yield connection.save_document(doc)

        except NotFoundError:
            yield connection.save_document(doc)
    defer.returnValue(connection)


@defer.inlineCallbacks
def solve(connection, doc_id):
    connection.info('Solving conflicts for document: %s', doc_id)

    plain_doc = yield connection.get_document(doc_id, raw=True,
                                              conflicts=True)
    if '_conflicts' not in plain_doc:
        connection.debug('Document:%s is not in state conflict, aborting.',
                         doc_id)
        return
    doc = connection._unserializer.convert(plain_doc)
    if not IDocument.providedBy(doc):
        handler = _solve_alert
    else:
        strategy_handlers = {
            ConflictResolutionStrategy.db_winner: _solve_db_winner,
            ConflictResolutionStrategy.alert: _solve_alert,
            ConflictResolutionStrategy.merge: _solve_merge}
        s = type(doc).conflict_resolution_strategy
        handler = strategy_handlers.get(s, _solve_alert)
        connection.debug("Using %s strategy", handler.__name__)

    try:
        yield handler(connection, doc, plain_doc['_conflicts'])
        connection.debug("Solving conflict for document %s completed", doc_id)
    except UnsolvableConflict:
        raise
    except Exception as e:
        error.handle_exception(None, e, "Failed solving conflict")
        raise UnsolvableConflict(str(e), doc)


def _solve_db_winner(connection, doc, conflicts):
    defers = list()
    for rev in conflicts:
        d = connection.delete_document({'_id': doc.doc_id, '_rev': rev})
        d.addErrback(Failure.trap, NotFoundError)
        defers.append(d)
    if defers:
        return defer.DeferredList(defers, consumeErrors=True)


def _solve_alert(connection, doc, conflicts):
    f = Failure(UnsolvableConflict("alert strategy", doc))
    return defer.fail(f)


@defer.inlineCallbacks
def _solve_merge(connection, doc, conflicts):
    # First check for the situation when no merge is actually needed.
    # This happens when the body of the conflicting documents is the same
    # only the revision is different.

    for rev in conflicts:
        fetched = yield connection.get_document(doc.doc_id, rev=rev)
        if not doc.compare_content(fetched):
            break
    else:
        connection.info('All the conflicting revisions of document: %s '
                        'are indeed the same, the only difference was in '
                        'meta fields. Picking db winner.', doc.doc_id)
        yield _solve_db_winner(connection, doc, conflicts)
        return

    # We actually have differences, lets resort to merging using the
    # update logs.
    logs = yield connection.query_view(
        UpdateLogs, **UpdateLogs.for_doc(doc.doc_id))
    # Some of the logs might be the result of solving the merge.
    # These logs contain other logs inside, which might have already been
    # cleaned up. Here we expand them.
    for log in list(logs):
        if log.handler is perform_merge:
            logs.extend(log.keywords['logs'])

    lookup = dict((x.rev_to, x) for x in logs)
    root_rev = _find_common_ancestor(lookup, [doc.rev] + conflicts)
    if not root_rev:
        raise UnsolvableConflict("Failed to find common ancestor", doc)

    try:
        root = yield connection.get_document(doc.doc_id, rev=root_rev)
    except NotFoundError:
        connection.debug('Cannot fetch root revision, the solution will '
                         'be composed based on db winner.')
        logs = list()
        for conflict in conflicts:
            try:
                logs.extend(_get_logs_between(root_rev, conflict, lookup))
            except ValueError as e:
                raise UnsolvableConflict(str(e), doc)
        root = doc

    # We remove previous mergies from the merge log, before above we
    # extracted individual logs forming there into the linear history
    logs = [x for x in lookup.itervalues()
            if x.handler is not perform_merge]
    logs.sort(key=operator.attrgetter('timestamp'))

    # We should remove any logs which we might have loaded from database
    # which created a revision which we would use a root, this is iterational
    # process

    def remove_target_rev(rev_to_remove):
        to_remove = first(x for x in logs if x.rev_to == rev_to_remove)
        if to_remove:
            logs.remove(to_remove)
            remove_target_rev(to_remove.rev_from)

    remove_target_rev(root_rev)

    try:
        yield connection.update_document(doc, perform_merge,
                                         root=root, logs=logs, rev=doc.rev)
    except Modified:
        connection.info("The document was modified while we were merging."
                        " I will restart the procedure.")
        yield solve(connection, doc.doc_id)
    else:
        # delete conflicting revisions
        yield _solve_db_winner(connection, doc, conflicts)


def perform_merge(document, root, logs, rev):
    if document.rev != rev:
        raise Modified()
    res = update.steps(root, *((x.handler, x.args, x.keywords) for x in logs))
    if res is None:
        return
    res.rev = rev
    return res


def _find_common_ancestor(lookup, revs):
    '''
    @param lookup: dict(rev->UpdateLog)
    '''
    history = dict()
    for rev in revs:
        history[rev] = list()
        rev_from = rev
        while True:
            history[rev].insert(0, rev_from)
            log = lookup.get(rev_from)
            if not log:
                break
            rev_from = log.rev_from
            if rev_from is None:
                # created revision
                break
    for candidate in reversed(history.values()[0]):
        if all(candidate in branch for branch in history.itervalues()):
            return candidate


def _get_logs_between(from_rev, to_rev, lookup):
    resp = list()
    rev = to_rev
    while True:
        log = lookup.get(rev)
        if not log:
            raise ValueError("Revision %s is missing in the lookup" %
                             (rev, ))
        resp.insert(0, log)
        rev = log.rev_from
        if rev is None:
            raise ValueError("Revision %s doesn't have ancestor" %
                             (log.rev_to, ))
        if rev == from_rev:
            break
    return resp


@defer.inlineCallbacks
def get_replication_status(rconnection, source):
    database = rconnection.database
    if not isinstance(database, driver.Database):
        raise TypeError("This procedure would work only for driver connected"
                        " to the real database. It uses public methods which"
                        " are not the part of IDatabaseDriver interface")

    version = yield rconnection.database.get_version()
    if version < (1, 2, 0):
        raise ValueError("CouchDB 1.2.0 required, found %r" % (version, ))

    active_tasks = yield database.couchdb_call(
        database.couchdb.get, '/_active_tasks')
    # In couchdb version >= 1.2.2 the replication_id is suffixed with
    # string literal '+continuous'. Here we cut it off
    for task in active_tasks:
        if (task.get('type') == 'replication' and
            task.get('replication_id', '').endswith('+continuous')):
            task['replication_id'] = task['replication_id'].replace(
                '+continuous', '')
    active_tasks = dict((x['replication_id'], x) for x in active_tasks
                        if (x['type'] == 'replication' and
                            'replication_id' in x))

    replications = yield rconnection.query_view(Replications,
                                                key=('source', source),
                                                include_docs=True)

    # target -> [(checkpointed_source_seq, continuous, status, replication_id)]
    result = dict()
    for replication in replications:
        target = replication['target']
        result.setdefault(target, list())

        r_id = replication['_replication_id']
        r_state = replication.get('_replication_state')
        r_continuous = replication.get('continuous', False)
        if r_state == 'completed':
            seq = replication['_replication_stats']['checkpointed_source_seq']
            result[target].append((seq, False, 'completed', r_id))
        elif r_state == 'triggered' and r_continuous:
            task = active_tasks.get(r_id)
            if not task:
                result[target].append((0, True, 'task_missing', r_id))
            else:
                seq = task['checkpointed_source_seq']
                result[target].append((seq, True, 'running', r_id))
        else:
            result[target].append((0, r_continuous, r_state, r_id))

    # Sort the results so that the first row for the target
    # is the row with the highest update_seq, aka the most
    # recent one. Secondary sorting is done to promote continuous
    # replication over the 1-time replication.
    for rows in result.itervalues():
        rows.sort(key=lambda x: (x[0], x[1]), reverse=True)

    defer.returnValue(result)


@defer.inlineCallbacks
def cleanup_logs(connection, rconnection):
    '''
    Perform a cleanup of update logs.
    This methods analazyes what replication are configured and removes
    the update logs which we will not need in future.
    It returns the C{int} counter of performed deletes.
    '''
    source = connection.database.db_name
    statuses = yield get_replication_status(rconnection, source)

    counters = dict((name, max([row[0] for row in replications]))
                    for name, replications in statuses.iteritems())
    cleanup_seq = min(counters.values()) if statuses else None
    own_tag = yield connection.get_database_tag()

    context = dict()
    context['deletes_count'] = 0 # this is returned as a result
    context['connection'] = connection

    # this is cleanup for the update logs created locally
    keys = UpdateLogs.until_seq(own_tag, cleanup_seq)
    rows = yield connection.query_view(UpdateLogs, **keys)

    @defer.inlineCallbacks
    def clean_local(context, row):
        connection = context['connection']
        in_conflict, raw_doc = yield _check_conflict(connection, row[1])
        if not in_conflict:
            context['deletes_count'] += 1
            yield _cleanup_update_log(connection, row[2])

    yield itask.coiterate((clean_local(context, row) for row in rows))

    # this is cleanup of the update logs imported from remote partinions
    # they should be cleaned up if the document is not in conflict state
    rows = yield connection.query_view(UpdateLogs, **UpdateLogs.all())
    grouped = _group_rows(rows,
                          # (partition_tag, owner_id)
                          key=lambda row: (row[0][1], row[0][2]),
                          # (rev, doc_id)
                          value=lambda row: (row[0][3], row[2]))

    @defer.inlineCallbacks
    def clean_imported(context, partition_tag, owner_id, entries):
        connection = context['connection']
        if partition_tag == own_tag:
            # this is local update log, this is handeled by the code above
            return

        in_conflict, raw_doc = yield _check_conflict(connection, owner_id)
        last_rev = entries[-1][0]
        if (not in_conflict and
            (raw_doc.get('_deleted') or
             parse_rev(last_rev) <= parse_rev(raw_doc['_rev']))):
            for (rev, doc_id) in entries:
                context['deletes_count'] += 1
                yield _cleanup_update_log(connection, doc_id)

    yield itask.coiterate((
        clean_imported(context, partition_tag, owner_id, entries)
        for (partition_tag, owner_id), entries in grouped.iteritems()))

    defer.returnValue(context['deletes_count'])


def parse_rev(rev):
    if '-' not in rev:
        raise ValueError("%r doesn't seem to be a rev" % (rev, ))
    seq, tag = rev.split('-', 1)
    seq = int(seq)
    return seq, tag


@defer.inlineCallbacks
def _check_conflict(connection, doc_id):
    try:
        raw_doc = yield connection.get_document(doc_id, raw=True,
                                                conflicts=True)
    except NotFoundError:
        in_conflict = False
        raw_doc = {'_id': doc_id, '_deleted': True}
    else:
        in_conflict = '_conflicts' in raw_doc
    defer.returnValue((in_conflict, raw_doc))


def _cleanup_update_log(connection, doc_id):
    d = connection.update_document(doc_id, update.delete)
    # this is normal if there is a concurrent cleanup running
    d.addErrback(Failure.trap, NotFoundError)
    return d


def _group_rows(rows, key, value):
    result = dict()
    for row in rows:
        key_ = key(row)
        value_ = value(row)
        result.setdefault(key_, [])
        result[key_].append(value_)
    return result
