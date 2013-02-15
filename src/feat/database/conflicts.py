import operator

from twisted.python.failure import Failure

from feat.agents.application import feat
from feat.common.text_helper import format_block
from feat.common import defer, error
from feat.database import view, driver, update

from feat.database.interface import NotFoundError, IDocument
from feat.database.interface import ConflictResolutionStrategy


class UnsolvableConflict(error.NonCritical):

    def __init__(self, msg, doc, *args, **kwargs):
        error.NonCritical.__init__(self, msg, *args, **kwargs)
        self.doc = doc

    log_level = 3
    log_line_template = "Failed solving conflit."


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


@feat.register_view
class UpdateLogs(view.JavascriptView):

    design_doc_id = 'featjs'
    name = 'update_logs'

    map = format_block('''
    function(doc) {
        if (doc[".type"] == "update_log") {
            emit(["by_rev", doc.owner_id, doc.rev_to], null);
            emit(["by_seq", doc.seq_num], null);
        }
    }''')

    @classmethod
    def for_doc(cls, doc_id):
        return dict(startkey=("by_rev", doc_id),
                    endkey=("by_rev", doc_id, {}),
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
def configure_replicator_database(host, port):
    """
    Connects to dabatase, checks the version and creates the
    design document used by feat (if it doesn't exist).
    @returns: (database, connection)
    """
    database = driver.Database(host, port, '_replicator')
    connection = database.get_connection()
    version = yield database.get_version()
    if version < (1, 1, 0):
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
    defer.returnValue((database, connection))


@defer.inlineCallbacks
def solve(connection, doc_id):
    connection.info('Solving conflicts for documnet: %s', doc_id)

    plain_doc = yield connection.get_document(doc_id, raw=True,
                                              conflicts='true')
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
    if defers:
        return defer.DeferredList(defers, consumeErrors=True)


def _solve_alert(connection, doc, conflicts):
    f = Failure(UnsolvableConflict("alert strategy", doc))
    return defer.fail(f)


@defer.inlineCallbacks
def _solve_merge(connection, doc, conflicts):
    logs = yield connection.query_view(
        UpdateLogs, **UpdateLogs.for_doc(doc.doc_id))
    lookup = dict((x.rev_to, x) for x in logs)
    root_rev = _find_common_ancestor(lookup, [doc.rev] + conflicts)
    if root_rev:
        try:
            root = yield connection.get_document(doc.doc_id, rev=root_rev)
        except NotFoundError:
            connection.debug('Cannot fetch root revision, the soluton will '
                             'be composed based on db winner.')
            logs = list()
            for conflict in conflicts:
                try:
                    logs.extend(_get_logs_between(root_rev, conflict, lookup))
                except ValueError as e:
                    raise UnsolvableConflict(str(e), doc)
            root = doc

        logs.sort(key=operator.attrgetter('timestamp'))
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
    else:
        raise UnsolvableConflict("Failed to find common ancestor", doc)


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
