# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.
import optparse
import os
import re

from twisted.internet import reactor

from feat.database import view, driver, document
from feat.agencies.net import options, config
from feat.common import log, defer, error, serialization
from feat.agents.application import feat
from feat import applications

from feat.database.interface import ConflictError
from feat.interface.serialization import IVersionAdapter


def reset_documents(snapshot):
    applications.get_initial_data_registry().reset(snapshot)


def get_current_initials():
    return applications.get_initial_data_registry().get_snapshot()


def create_connection(host, port, name, username=None, password=None):
    db = driver.Database(host, int(port), name, username, password)
    return db.get_connection()


@defer.inlineCallbacks
def push_initial_data(connection, overwrite=False, push_design_docs=True):
    documents = applications.get_initial_data_registry().itervalues()
    for doc in documents:
        try:
            yield connection.save_document(doc)
        except ConflictError:
            fetched = yield connection.get_document(doc.doc_id)
            if fetched.compare_content(doc):
                continue
            if not overwrite:
                log.warning('script', 'Document with id %s already exists! '
                            'Use --force, Luck!', doc.doc_id)
            else:
                log.info('script', 'Updating old version of the document, '
                         'id: %s', doc.doc_id)
                rev = yield connection.get_revision(doc.doc_id)
                doc.rev = rev
                yield connection.save_document(doc)

    if not push_design_docs:
        return
    design_docs = view.generate_design_docs()
    for design_doc in design_docs:
        try:
            yield connection.save_document(design_doc)
        except ConflictError:
            fetched = yield connection.get_document(design_doc.doc_id)
            if fetched.compare_content(design_doc):
                continue

            log.warning('script', 'The design document %s changed. '
                        'Use "feat-service upgrade" to push the new revisions '
                        'and restart the service in organised manner.',
                        design_doc.doc_id)

            # calculate a diff for debugging purpose
            diffs = dict()
            for what in ('views', 'filters'):
                diffs[what] = dict()
                a = getattr(design_doc, what)
                b = getattr(fetched, what)
                diff = set(a.keys()) - set(b.keys())
                for key in diff:
                    diffs[what][key] = (a[key], None)
                diff = set(b.keys()) - set(a.keys())
                for key in diff:
                    diffs[what][key] = (None, b[key])

                for name in set(a.keys()).intersection(set(b.keys())):
                    if a[name] != b[name]:
                        diffs[what][name] = (a[name], b[name])

            def strcode(x):
                if not x:
                    return ''
                if isinstance(x, (str, unicode)):
                    return x
                return "\n".join("%s: %s" % t for t in x.items())

            for what in diffs:
                for name in diffs[what]:
                    log.info('script',
                             '%s code changed. \nOLD: \n%s\n\nNEW:\n%s\n',
                             what, strcode(diffs[what][name][1]),
                             strcode(diffs[what][name][0]))


@defer.inlineCallbacks
def _update_old(connection, doc):
    doc_id = doc.doc_id
    log.info('script', 'Updating old version of the document, id: %s', doc_id)
    rev = yield connection.get_revision(doc_id)
    doc.rev = rev
    yield connection.save_document(doc)


def parse_options(parser=None, args=None):
    if parser is None:
        parser = optparse.OptionParser()
        options.add_general_options(parser)
        options.add_db_options(parser)
        parser.add_option('-f', '--force', dest='force', default=False,
                          help=('Overwrite documents which are '
                                'already in the database.'),
                          action="store_true")
        parser.add_option('-m', '--migration', dest='migration', default=False,
                          help='Run migration script.',
                          action="store_true")

    opts, args = parser.parse_args(args)
    opts.db_host = opts.db_host or options.DEFAULT_DB_HOST
    opts.db_port = opts.db_port or options.DEFAULT_DB_PORT
    opts.db_name = opts.db_name or options.DEFAULT_DB_NAME
    return opts, args


def create_db(connection):

    def display_warning(f):
        if 'file_exists' in str(f.value):
            return
        log.warning('script', 'Creating of database failed, reason: %s',
                    f.value)

    d = connection.create_database()
    d.addErrback(display_warning)
    return d


def script():
    log.init()
    log.FluLogKeeper.set_debug('4')

    opts, args = parse_options()
    c = config.DbConfig(host=opts.db_host, port=opts.db_port,
                        name=opts.db_name, username=opts.db_username,
                        https=opts.db_https, password=opts.db_password)
    with dbscript(c) as d:

        def body(connection):
            documents = applications.get_initial_data_registry().itervalues()
            log.info('script', "I will push %d documents.",
                     len(list(documents)))
            d = create_db(connection)
            d.addCallback(defer.drop_param, push_initial_data, connection,
                          opts.force)
            if opts.migration:
                d.addCallback(defer.drop_param, migration_script, connection)
            return d

        d.addCallback(body)


def tupletize_version(version_string):
    '''
    Given "1.2.3-6" returns a tuple of (1, 2, 3, 6).
    This is used for sorting versions.
    '''
    return tuple(int(x) for x in re.findall(r'[0-9]+', version_string))


@defer.inlineCallbacks
def migration_script(connection):
    log.info("script", "Running the migration script.")
    index = yield connection.query_view(view.DocumentByType,
                                        group_level=2, parse_result=False)
    try:
        for (type_name, version), count in index:
            restorator = serialization.lookup(type_name)
            if not restorator:
                log.error(
                    'script', "Failed to lookup the restorator for the "
                    "type name: %s. There is %d objects like this in the"
                    " database. They will not be migrated.", type_name,
                    count)

            if (IVersionAdapter.providedBy(restorator) and
                ((version is None and restorator.version > 1) or
                 (version is not None and version < restorator.version))):
                log.info('script', "I will migrate %d documents of the "
                          "type: %s from version %s to %d", count,
                          type_name, version, restorator.version)

                migrated = 0
                while migrated < count:
                    fetched = yield connection.query_view(
                        view.DocumentByType,
                        key=(type_name, version),
                        limit=15,
                        reduce=False,
                        include_docs=True)

                    migrated += len(fetched)
                    if not migrated:
                        break
                log.info("script", "Migrated %d documents of the type %s "
                         "from %s version to %s", migrated, type_name,
                         version, restorator.version)

    except Exception:
        error.handle_exception("script", None,
                               "Failed running migration script")
        raise


class dbscript(object):

    def __init__(self, dbconfig):
        log.debug('dbscript', '__init__')
        assert isinstance(dbconfig, config.DbConfig), str(type(dbconfig))
        self.config = dbconfig

    def __enter__(self):
        log.debug('dbscript', '__enter__')
        self.connection = create_connection(
            self.config.host, self.config.port, self.config.name,
            self.config.username, self.config.password)

        log.info('script', "Using host: %s, port: %s, db_name; %s",
                 self.config.host, self.config.port, self.config.name)

        self._deferred = defer.Deferred()
        return self._deferred

    def _handle_error(self, fail):
        error.handle_failure('script', fail, 'Error in the end')

    def __exit__(self, type, value, traceback):
        log.debug('dbscript', '__exit__')
        self._deferred.addCallback(lambda _:
            log.debug('dbscript', 'deferred callback'))
        self._deferred.addErrback(self._handle_error)
        self._deferred.addBoth(defer.drop_param,
                               self.connection.database.disconnect)
        self._deferred.addBoth(defer.drop_param, reactor.stop)
        def caller():
            log.debug('dbscript', 'calling callback on deferred %r',
                self._deferred)
            self._deferred.callback(self.connection)
        reactor.callWhenRunning(caller)
        log.debug('dbscript', 'running reactor')
        reactor.run()
        log.debug('dbscript', 'ran reactor')


@feat.register_restorator
class ApplicationVersion(document.Document):

    type_name = 'application-version'

    document.field("name", None)
    document.field("version", None)


def standalone(script, options=[]):

    def define_options(extra_options):
        c = config.parse_service_config()

        parser = optparse.OptionParser()
        parser.add_option('--dbhost', '-H', action='store', dest='db_host',
                          type='str', help='hostname of the database',
                          default=c.db.host)
        parser.add_option('--dbname', '-n', action='store', dest='db_name',
                          type='str', help='name of database to use',
                          default=c.db.name)
        parser.add_option('--dbport', '-P', action='store', dest='db_port',
                          type='str', help='port of database to use',
                          default=c.db.port)
        parser.add_option('--dbusername', dest="db_username",
                          help="username to use for authentication ",
                          metavar="USER", default=c.db.username)
        parser.add_option('--dbpassword', dest="db_password",
                          help="password to use for authentication ",
                          metavar="PASSWORD", default=c.db.password)
        parser.add_option('--log', action='store', dest='log',
                          type='str', help='log level to set',
                          default=os.environ.get('FEAT_DEBUG', '2'))

        for option in extra_options:
            parser.add_option(option)
        return parser

    def _error_handler(fail):
        error.handle_failure('script', fail, "Finished with exception: ")

    # call log.init before define_option, which parses the service config
    # and can fail
    log.init()
    parser = define_options(options)
    opts, args = parser.parse_args()
    log.FluLogKeeper.set_debug(opts.log)

    db = config.parse_service_config().db
    db.host, db.port, db.name = opts.db_host, opts.db_port, opts.db_name
    db.username, db.password = opts.db_username, opts.db_password

    with dbscript(db) as d:
        d.addCallback(script, opts)
        d.addErrback(_error_handler)


@defer.inlineCallbacks
def view_aterator(connection, callback, view, view_keys=dict(),
                  args=tuple(), kwargs=dict(), per_page=15,
                  consume_errors=True):
    '''
    Asynchronous iterator for the view. Downloads a view in pages
    and calls the callback for each row.
    This helps avoid transfering data in huge datachunks.
    '''
    skip = 0
    while True:
        keys = dict(view_keys)
        keys.update(dict(skip=skip, limit=per_page))
        records = yield connection.query_view(view, **keys)
        log.debug('view_aterator', "Fetched %d records of the view: %s",
                  len(records), view.name)
        skip += len(records)
        for record in records:
            try:
                yield callback(connection, record, *args, **kwargs)
            except Exception as e:
                error.handle_exception(
                    'view_aterator', e,
                    "Callback %s failed its iteration on a row %r",
                    callback.__name__, record)
                if not consume_errors:
                    raise e

        if not records:
            break
