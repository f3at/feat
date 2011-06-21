import copy
import optparse

from twisted.internet import defer, reactor

from feat.agents.base import document, view
from feat.agencies.net import database
from feat.agencies.interface import ConflictError
from feat.common import log


_documents = []


def reset_documents(documents):
    global _documents

    _documents = documents


def get_current_initials():
    global _documents
    return copy.deepcopy(_documents)


def initial_data(doc):
    global _documents

    if callable(doc) and issubclass(doc, document.Document):
        doc = doc()
    if not isinstance(doc, document.Document):
        raise AttributeError(
            'First argument needs to be an instance or class of something '
            'inheriting from feat.agents.base.document.Document!')
    if doc.doc_id:
        for x in _documents:
            if x.doc_id == doc.doc_id:
                _documents.remove(x)
    _documents.append(doc)


def create_connection(host, port, name):
    db = database.Database(host, port, name)
    return db.get_connection()


@defer.inlineCallbacks
def push_initial_data(connection):
    global _documents

    for doc in _documents:
        try:
            yield connection.save_document(doc)
        except ConflictError:
            log.error('script', 'Document with id %s already exists!',
                      doc.doc_id)

    design = view.generate_design_doc()
    yield connection.save_document(design)


DEFAULT_DB_HOST = database.DEFAULT_DB_HOST
DEFAULT_DB_PORT = database.DEFAULT_DB_PORT
DEFAULT_DB_NAME = database.DEFAULT_DB_NAME


def parse_options():
    usage = "%prog -H host -P port -N name push"
    parser = optparse.OptionParser(usage)
        # database related options
    parser.add_option('-H', '--dbhost', dest="db_host",
                      help="host of database server to connect to",
                      metavar="HOST", default=DEFAULT_DB_HOST)
    parser.add_option('-P', '--dbport', dest="db_port",
                      help="port of messaging server to connect to",
                      metavar="PORT", default=DEFAULT_DB_PORT, type="int")
    parser.add_option('-N', '--dbname', dest="db_name",
                      help="host of database server to connect to",
                      metavar="NAME", default=DEFAULT_DB_NAME)
    return parser.parse_args()


def create_db(connection):

    def display_warning(f):
        log.warning('script', 'Creating of database failed, reason: %s',
                    f.value)

    d = connection.create_database()
    d.addErrback(display_warning)
    return d


def script():
    with dbscript() as (d, args):

        def body(connection):
            log.info('script', "I will push %d documents.", len(_documents))
            d = create_db(connection)
            d.addCallback(lambda _: push_initial_data(connection))
            return d

        d.addCallback(body)


class dbscript(object):

    def __enter__(self):
        opts, args = parse_options()
        self.connection = create_connection(
            opts.db_host, opts.db_port, opts.db_name)

        log.FluLogKeeper.init()
        log.FluLogKeeper.set_debug('5')
        log.info('script', "Using host: %s, port: %s, db_name; %s",
                 opts.db_host, opts.db_port, opts.db_name)
        self._deferred = defer.Deferred()
        return self._deferred, args

    def __exit__(self, type, value, traceback):
        self._deferred.addBoth(lambda _: reactor.stop())
        reactor.callWhenRunning(self._deferred.callback, self.connection)
        reactor.run()
