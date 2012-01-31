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
import copy
import optparse

from twisted.internet import reactor

from feat.agents.base import document, view
from feat.agencies.net import options, database
from feat.agencies.interface import ConflictError
from feat.common import log, defer


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

    design_docs = view.generate_design_docs()
    for design_doc in design_docs:
        yield connection.save_document(design_doc)


def parse_options():
    parser = optparse.OptionParser()
    options.add_general_options(parser)
    options.add_db_options(parser)
    opts, args = parser.parse_args()
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
    with dbscript() as (d, args):

        def body(connection):
            log.info('script', "I will push %d documents.", len(_documents))
            d = create_db(connection)
            d.addCallback(defer.drop_param, push_initial_data, connection)
            return d

        d.addCallback(body)


class dbscript(object):

    def __enter__(self):
        log.init()
        log.FluLogKeeper.set_debug('5')

        opts, args = parse_options()
        self.connection = create_connection(
            opts.db_host, opts.db_port, opts.db_name)

        log.info('script', "Using host: %s, port: %s, db_name; %s",
                 opts.db_host, opts.db_port, opts.db_name)
        self._deferred = defer.Deferred()
        return self._deferred, args

    def __exit__(self, type, value, traceback):
        self._deferred.addBoth(defer.drop_param, reactor.stop)
        reactor.callWhenRunning(self._deferred.callback, self.connection)
        reactor.run()
