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
import sys
import os

from zope.interface import implements
from twisted.web import error as web_error
from twisted.internet import error
from twisted.web._newclient import ResponseDone
from twisted.python import failure

from feat.agencies.database import Connection, ChangeListener
from feat.common import log, defer, time
from feat.agencies import common

from feat.agencies.interface import *
from feat.interface.view import *


from feat import extern
# Add feat/extern/paisley to the load path
sys.path.insert(0, os.path.join(extern.__path__[0], 'paisley'))
from paisley.changes import ChangeNotifier
from paisley.client import CouchDB


DEFAULT_DB_HOST = "localhost"
DEFAULT_DB_PORT = 5984
DEFAULT_DB_NAME = "feat"


class Database(common.ConnectionManager, log.LogProxy, ChangeListener):

    implements(IDbConnectionFactory, IDatabaseDriver)

    log_category = "database"

    def __init__(self, host, port, db_name):
        common.ConnectionManager.__init__(self)
        log.LogProxy.__init__(self, log.FluLogKeeper())
        ChangeListener.__init__(self, self)

        self.semaphore = defer.DeferredSemaphore(1)
        self.paisley = None
        self.db_name = None
        self.host = None
        self.port = None
        self.notifier = None

        self.retry = 0
        self.reconnector = None

        self._configure(host, port, db_name)

    def reconfigure(self, host, port, name):
        if self.notifier.isRunning():
            self.notifier.stop()
        self._configure(host, port, name)
        self._setup_notifier()

    def show_connection_status(self):
        eta = self.reconnector and self.reconnector.active() and \
              time.left(self.reconnector.getTime())
        return "CouchDB", self.is_connected(), self.host, self.port, eta

    ### IDbConnectionFactory

    def get_connection(self):
        return Connection(self)

    ### IDatabaseDriver

    def open_doc(self, doc_id):
        return self._paisley_call(self.paisley.openDoc, self.db_name, doc_id)

    def save_doc(self, doc, doc_id=None):
        return self._paisley_call(self.paisley.saveDoc,
                                  self.db_name, doc, doc_id)

    def delete_doc(self, doc_id, revision):
        return self._paisley_call(self.paisley.deleteDoc,
                                  self.db_name, doc_id, revision)

    def create_db(self):
        return self._paisley_call(self.paisley.createDB,
                                  self.db_name)

    def listen_changes(self, doc_ids, callback):
        d = ChangeListener.listen_changes(self, doc_ids, callback)
        d.addCallback(defer.bridge_param, self._setup_notifier)
        return d

    def cancel_listener(self, listener_id):
        ChangeListener.cancel_listener(self, listener_id)
        return self._setup_notifier()

    def query_view(self, factory, **options):
        factory = IViewFactory(factory)
        d = self._paisley_call(self.paisley.openView,
                               self.db_name, DESIGN_DOC_ID, factory.name,
                               **options)
        d.addCallback(self._parse_view_result)
        return d

    ### paisleys ChangeListener interface

    def changed(self, change):
        # The change parameter is just an ugly effect of json unserialization
        # of the couchdb output. It can be many different things, hence the
        # strange logic above.
        if "changes" in change:
            doc_id = change['id']
            for line in change['changes']:
                # The changes are analized when there is not http request
                # pending. Otherwise it can result in race condition problem.
                deleted = line.get('deleted', False)
                self.semaphore.run(self._trigger_change,
                                   doc_id, line['rev'], deleted)
        else:
            self.info('Bizare notification received from CouchDB: %r', change)

    def connectionLost(self, reason):
        if reason.check(error.ConnectionDone):
            # expected just pass
            return
        elif reason.check(ResponseDone):
            self.debug("CouchDB closed the notification listener. This might "
                       "indicate missconfiguration. Take look at it")
            return
        elif reason.check(error.ConnectionRefusedError):
            self.retry += 1
            wait = min(2**(self.retry - 1), 300)
            self.debug('CouchDB refused connection for %d time. '
                       'This indicates missconfiguration or temporary '
                       'network problem. Will try to reconnect in %d seconds.',
                       self.retry, wait)
            self.reconnector = time.callLater(wait, self._setup_notifier)
            self._on_disconnected()
            return
        else:
            # FIXME handle disconnection when network is down
            self._on_disconnected()
            self.warning('Connection to db lost with reason: %r', reason)
            return self._setup_notifier()

    ### private

    def _configure(self, host, port, name):
        self._cancel_reconnector()
        self.host, self.port = host, port
        self.paisley = CouchDB(host, port)
        self.db_name = name
        self.notifier = ChangeNotifier(self.paisley, self.db_name)
        self.notifier.addListener(self)

        # ping database to figure trigger changing state to connected
        d = self._paisley_call(self.paisley.listDB)
        d.addErrback(failure.Failure.trap, NotConnectedError)

    def _parse_view_result(self, resp):
        assert "rows" in resp

        for row in resp["rows"]:
            yield row["key"], row["value"]

    def _setup_notifier(self):
        doc_ids = self._extract_doc_ids()
        self.log('Setting up the notifier passing. Doc_ids: %r.',
                 doc_ids)
        if self.notifier.isRunning():
            self.notifier.stop()
        if len(doc_ids) == 0:
            # Don't run listner if it is not needed,
            # cancel reconnector if one is running.
            if self.reconnector and self.reconnector.active():
                self.reconnector.cancel()
                self.reconnector = None
            return

        d = self.notifier.start(
            heartbeat=1000)
        d.addCallback(self._connected)
        d.addErrback(self.connectionLost)
        d.addErrback(failure.Failure.trap, NotConnectedError)
        return d

    def _connected(self, _):
        self.debug('Established persistent connection for receiving '
                   'notifications.')
        self._on_connected()
        self._cancel_reconnector()

    def _cancel_reconnector(self):
        if self.reconnector:
            if self.reconnector.active():
                self.reconnector.cancel()
            self.reconnector = None
            self.retry = 0

    def _paisley_call(self, method, *args, **kwargs):
        # It is necessarry to acquire the lock to perform the http request
        # because we need to be sure that we are not in the middle of sth
        # while analizing the change notification
        d = self.semaphore.run(method, *args, **kwargs)
        d.addCallback(defer.bridge_param, self._on_connected)
        d.addErrback(self._error_handler)
        return d

    def _error_handler(self, failure):
        exception = failure.value
        msg = failure.getErrorMessage()
        if isinstance(exception, web_error.Error):
            status = int(exception.status)
            if status == 409:
                raise ConflictError(msg)
            elif status == 404:
                raise NotFoundError(msg)
            else:
                self.info(exception.response)
                raise NotImplementedError(
                    'Behaviour for response code %d not define yet, FIXME!' %
                    status)
        elif failure.check(error.ConnectionRefusedError):
            self._on_disconnected()
            raise NotConnectedError("Database connection refused.")
        else:
            failure.raiseException()
