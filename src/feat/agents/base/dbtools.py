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

from twisted.internet import reactor

from feat.agents.base import view
from feat.agencies.net import options, database, config
from feat.agencies.interface import ConflictError
from feat.common import log, defer, error
from feat.agents.application import feat
from feat import applications


def reset_documents(snapshot):
    applications.get_initial_data_registry().reset(snapshot)


def get_current_initials():
    return applications.get_initial_data_registry().get_snapshot()


def create_connection(host, port, name):
    db = database.Database(host, port, name)
    return db.get_connection()


@defer.inlineCallbacks
def push_initial_data(connection, overwrite=False):
    documents = applications.get_initial_data_registry().itervalues()
    for doc in documents:
        try:
            yield connection.save_document(doc)
        except ConflictError:
            if not overwrite:
                log.error('script', 'Document with id %s already exists!',
                          doc.doc_id)
            else:
                yield _delete_old(connection, doc.doc_id)
                yield connection.save_document(doc)

    design_docs = view.generate_design_docs()
    for design_doc in design_docs:
        try:
            yield connection.save_document(design_doc)
        except ConflictError:
            yield _delete_old(connection, design_doc.doc_id)
            yield connection.save_document(design_doc)


@defer.inlineCallbacks
def _delete_old(connection, doc_id):
    log.info('script', 'Deleting old version of the document, id: %s', doc_id)
    old = yield connection.get_document(doc_id)
    yield connection.delete_document(old)


def load_application(option, opt_str, value, parser):
    splited = value.split('.')
    module, name = '.'.join(splited[:-1]), splited[-1]
    applications.load(module, name)


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
        parser.add_option('-a', '--application', nargs=1,
                          callback=load_application, type="string",
                          help='Load application by canonical name.',
                          action="callback")


    opts, args = parser.parse_args(args)
    opts.db_host = opts.db_host or options.DEFAULT_DB_HOST
    opts.db_port = opts.db_port or options.DEFAULT_DB_PORT
    opts.db_name = opts.db_name or options.DEFAULT_DB_NAME
    return opts, args


def create_db(connection):

    def display_warning(f):
        log.warning('script', 'Creating of database failed, reason: %s',
                    f.value)

    d = connection.create_database()
    d.addErrback(display_warning)
    return d


def script():
    log.init()
    log.FluLogKeeper.set_debug('5')

    opts, args = parse_options()
    c = config.DbConfig(host=opts.db_host, port=opts.db_port,
                        name=opts.db_name)
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


@defer.inlineCallbacks
def migration_script(connection):
    log.info("script", "Running the migration script.")
    to_migrate = yield connection.query_view(VersionedDocuments)
    log.info("script", "%d documents will be updated.", len(to_migrate))
    for doc_id in to_migrate:
        try:
            doc = yield connection.get_document(doc_id)
            # unserializing the document promotes it to new version
            yield connection.save_document(doc)
        except Exception, e:
            error.handle_exception(None, e, "Failed saving migrated document")


class dbscript(object):

    def __init__(self, dbconfig):
        assert isinstance(dbconfig, config.DbConfig), str(type(dbconfig))
        self.config = dbconfig

    def __enter__(self):
        self.connection = create_connection(
            self.config.host, self.config.port, self.config.name)

        log.info('script', "Using host: %s, port: %s, db_name; %s",
                 self.config.host, self.config.port, self.config.name)

        self._deferred = defer.Deferred()
        return self._deferred

    def __exit__(self, type, value, traceback):
        self._deferred.addBoth(defer.drop_param, reactor.stop)
        reactor.callWhenRunning(self._deferred.callback, self.connection)
        reactor.run()


@feat.register_view
class VersionedDocuments(view.BaseView):

    name = 'versioned_documents'

    def map(doc):
        if '.version' in doc:
            yield None, doc.get('_id')
