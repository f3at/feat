from feat.agents.application import feat
from feat.common.text_helper import format_block
from feat.common import defer
from feat.database import view, driver

from feat.database.interface import NotFoundError


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
        raise ValueError("Required at least couchdb 1.1.0, found: %r" %
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
