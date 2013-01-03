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
import urllib
import os
import sys

from zope.interface import implements
from twisted.web import error as web_error
from twisted.internet import error
from twisted.web._newclient import ResponseDone
from twisted.python import failure

from feat.database.client import Connection, ChangeListener
from feat.common import log, defer, time
from feat.agencies import common

from feat.database.interface import IDatabaseDriver, IDbConnectionFactory
from feat.database.interface import NotFoundError, NotConnectedError
from feat.database.interface import ConflictError, IViewFactory
from feat.database.interface import IAttachmentPrivate

from feat import extern
# Add feat/extern/paisley to the load path
sys.path.insert(0, os.path.join(extern.__path__[0], 'paisley'))

from paisley.changes import ChangeNotifier
from paisley.client import CouchDB, json as pjson


DEFAULT_DB_HOST = "localhost"
DEFAULT_DB_PORT = 5985
DEFAULT_DB_NAME = "feat"


class Notifier(object):

    def __init__(self, db, filter_):
        self._db = db
        self._filter = filter_
        self.name = self._filter.name
        self._params = None

        self.reconfigure()

    def reconfigure(self):
        # called after changing the database
        self._changes = ChangeNotifier(self._db.paisley, self._db.db_name)
        self._changes.addListener(self)

    def setup(self):
        new_params = self._filter.extract_params()
        if self._params is not None and \
           new_params == self._params and \
           self._changes.isRunning():
            return defer.succeed(None)

        self._params = new_params

        if self._changes.isRunning():
            self._changes.stop()
        d = defer.succeed(None)
        if new_params is not None:
            d.addCallback(defer.drop_param, self._db.wait_connected)
            d.addCallback(defer.drop_param, self._changes.start,
                           heartbeat=1000, **new_params)
        else:
            self._db.log("Stopping notifier: %r", self.name)
        d.addErrback(self.connectionLost)
        d.addErrback(failure.Failure.trap, NotConnectedError)
        return d

    ### paisleys ChangeListener interface

    def changed(self, change):
        # The change parameter is just an ugly effect of json unserialization
        # of the couchdb output. It can be many different things, hence the
        # strange logic above.
        if "changes" in change:
            doc_id = change['id']
            deleted = change.get('deleted', False)
            for line in change['changes']:
                # The changes are analized when there is not http request
                # pending. Otherwise it can result in race condition problem.
                self._db.process_notifications(
                    self._filter, doc_id, line['rev'], deleted)
        else:
            self.info('Bizare notification received from CouchDB: %r', change)

    def connectionLost(self, reason):
        self._db.connectionLost(reason)


class Database(common.ConnectionManager, log.LogProxy, ChangeListener):

    implements(IDbConnectionFactory, IDatabaseDriver)

    log_category = "database"

    def __init__(self, host, port, db_name):
        common.ConnectionManager.__init__(self)
        log.LogProxy.__init__(self, log.get_default() or log.FluLogKeeper())
        ChangeListener.__init__(self, self)

        self.paisley = None
        self.db_name = None
        self.host = None
        self.port = None
        # name -> Notifier
        self.notifiers = dict()

        self.retry = 0
        self.reconnector = None

        # doc_id -> list of tuples (Filter, rev, deleted)
        # The list is added when we start modifying the document,
        # all the notificactions received in the meantime will be
        # stored in this hash, until change is done, this solves
        # the problem with caused by change notification received
        # before the http request modifying the document is finished
        self._pending_notifications = dict()
        # doc_id -> C{int} number of locks
        self._document_locks = dict()

        self._configure(host, port, db_name)

    def reconfigure(self, host, port, name):
        self._configure(host, port, name)

    def show_connection_status(self):
        eta = self.reconnector and self.reconnector.active() and \
              time.left(self.reconnector.getTime())
        return "CouchDB", self.is_connected(), self.host, self.port, eta

    def show_document_locks(self):
        return dict(self._document_locks), dict(self._pending_notifications)

    ### IDbConnectionFactory

    def get_connection(self):
        return Connection(self)

    ### IDatabaseDriver

    def open_doc(self, doc_id):
        return self._paisley_call(doc_id, self.paisley.openDoc,
                                  self.db_name, doc_id)

    def save_doc(self, doc, doc_id=None):
        return self._lock_document(doc_id, self._paisley_call,
                                   doc_id, self.paisley.saveDoc,
                                   self.db_name, doc, doc_id)

    def delete_doc(self, doc_id, revision):
        return self._lock_document(doc_id, self._paisley_call,
                                   doc_id, self.paisley.deleteDoc,
                                   self.db_name, doc_id, revision)

    def create_db(self):
        return self._paisley_call(self.db_name, self.paisley.createDB,
                                  self.db_name)

    def delete_db(self):
        return self._paisley_call(self.db_name, self.paisley.deleteDB,
                                  self.db_name)

    def replicate(self, source, target, **options):
        uri = '/_replicate'
        body = dict(source=source, target=target)
        body.update(options)
        return self._paisley_call(self.db_name, self.paisley.post,
                                  uri, body, 'replicate')

    def disconnect(self):
        self._cancel_reconnector()

    # listen_chagnes from ChangeListener

    # cancel_listener from ChangeListener

    def query_view(self, factory, **options):
        factory = IViewFactory(factory)
        d = self._paisley_call(factory.design_doc_id,
                               self.paisley.openView,
                               self.db_name, factory.design_doc_id,
                               factory.name, **options)
        d.addCallback(self._parse_view_result)
        return d

    def save_attachment(self, doc_id, revision, attachment):
        attachment = IAttachmentPrivate(attachment)
        uri = ('/%s/%s/%s?rev=%s' %
               (self.db_name, urllib.quote(doc_id.encode('utf-8')),
                urllib.quote(attachment.name), revision.encode('utf-8')))
        headers = {'Content-Type': [attachment.content_type]}
        body = attachment.get_body()
        if isinstance(body, unicode):
            body = body.encode('utf-8')
        d = self._lock_document(doc_id, self._paisley_call, doc_id,
                                self.paisley.put, uri,
                                body, headers=headers)
        d.addCallback(self.paisley.parseResult)
        return d

    def get_attachment(self, doc_id, name):
        uri = ('/%s/%s/%s' %
               (self.db_name, urllib.quote(doc_id.encode('utf-8')),
                urllib.quote(name)))
        headers = {'Accept': ['*/*']}
        return self._paisley_call(doc_id, self.paisley.get,
                                  uri, headers=headers)

    def get_update_seq(self):
        d = self._paisley_call('update_seq', self.paisley.infoDB, self.db_name)
        d.addCallback(lambda x: x['update_seq'])
        return d

    def get_changes(self, filter_, limit=None, since=0):
        params = dict(since=since)
        if limit is not None:
            params['limit'] = limit
        if filter_ is not None:
            params['filter'] = str('%s/%s' % (filter_.view.design_doc_id,
                                              filter_.view.name))
        url = str('/%s/_changes?%s' % (self.db_name, urllib.urlencode(params)))
        d = self._paisley_call('get_changes', self.paisley.get, url)
        d.addCallback(self.paisley.parseResult)
        return d

    def bulk_get(self, doc_ids):
        body = dict(keys=doc_ids)
        url = '/%s/_all_docs?include_docs=true' % (self.db_name, )
        d = self._paisley_call('bulk_get', self.paisley.post,
                               url, pjson.dumps(body))
        d.addCallback(self.paisley.parseResult)
        return d

    ### public ###

    def reconnect(self):
        # ping database to figure trigger changing state to connected
        if self.reconnector is None or not self.reconnector.active():
            self.retry += 1
            wait = min(2**(self.retry - 1), 300)
            if self.retry > 1:
                self.debug('CouchDB refused connection for %d time. '
                           'This indicates misconfiguration or temporary '
                           'network problem. Will try to reconnect in '
                           '%d seconds.', self.retry, wait)
            d = defer.Deferred()
            d.addCallback(defer.drop_param, self._paisley_call,
                           None, self.paisley.listDB)
            d.addErrback(failure.Failure.trap, NotConnectedError)
            self.reconnector = time.callLater(wait, d.callback, None)
            return d
        else:
            return self.wait_connected()

    def connectionLost(self, reason):
        if reason.check(error.ConnectionDone):
            # expected just pass
            return
        elif reason.check(ResponseDone):
            self.debug("CouchDB closed the notification listener. This might "
                       "indicate misconfiguration. Take a look at it.")
            return
        elif reason.check(error.ConnectionRefusedError):
            self.reconnect()
            return
        else:
            # FIXME handle disconnection when network is down
            self._on_disconnected()
            self.warning('Connection to db lost with reason: %r', reason)
            self.reconnect()
            return self._setup_notifiers()

    ### used by Notifier ###

    def process_notifications(self, filter, doc_id, rev, deleted):
        if doc_id not in self._pending_notifications:
            filter.notified(doc_id, rev, deleted)
        else:
            self._pending_notifications[doc_id].append((filter, rev, deleted))

    ### private

    def _lock_document(self, doc_id, method, *args, **kwargs):
        lock_value = self._document_locks.get(doc_id, 0) + 1
        self._document_locks[doc_id] = lock_value

        if lock_value == 1:
            assert doc_id not in self._pending_notifications, \
                   "lock_value == 1 and _pending_notifications has a entry"\
                   ". Something is leaking."
            self._pending_notifications[doc_id] = list()

        d = method(*args, **kwargs)
        d.addBoth(defer.bridge_param, self._unlock_document, doc_id)
        return d

    def _unlock_document(self, doc_id):
        lock_value = self._document_locks.get(doc_id, None)
        assert lock_value is not None, \
               "_unlock_document() called, but counter is not there!"
        lock_value -= 1

        if lock_value == 0:
            del(self._document_locks[doc_id])
            notifications = self._pending_notifications.pop(doc_id, None)
            assert notifications is not None, \
                   "Lock value reached 0 but there is no pending_notifications"
            for filter, rev, deleted in notifications:
                filter.notified(doc_id, rev, deleted)
        else:
            self._document_locks[doc_id] = lock_value

    def _paisley_call(self, tag, method, *args, **kwargs):
        d = method(*args, **kwargs)
        d.addCallback(defer.bridge_param, self._on_connected)
        d.addErrback(self._error_handler, tag)
        return d

    def _configure(self, host, port, name):
        self._cancel_reconnector()
        self.host, self.port = host, port
        self.paisley = CouchDB(host, port)
        self.db_name = name

        self._pending_notifications.clear()
        self._document_locks.clear()

        [notifier.reconfigure() for notifier in self.notifiers.values()]
        self.reconnect()
        self._setup_notifiers()

    def _parse_view_result(self, resp):
        assert "rows" in resp

        for row in resp["rows"]:
            if "id" in row:
                if "doc" in row:
                    # querying with include_docs=True
                    yield row["key"], row["value"], row["id"], row["doc"]
                else:
                    # querying without reduce
                    yield row["key"], row["value"], row["id"]
            else:
                # querying with reduce
                yield row["key"], row["value"]

    def _setup_notifiers(self):
        defers = list()
        for notifier in self.notifiers.values():
            defers.append(notifier.setup())
        return defer.DeferredList(defers, consumeErrors=True)

    def _setup_notifier(self, filter_):
        self.log('Setting up the notifier %s', filter_.name)
        notifier = self.notifiers.get(filter_.name) or Notifier(self, filter_)
        self.notifiers[filter_.name] = notifier

        return notifier.setup()

    def _on_connected(self):
        common.ConnectionManager._on_connected(self)
        self._cancel_reconnector()

    def _cancel_reconnector(self):
        if self.reconnector:
            self.debug("Reconnected to couchdb.")
            if self.reconnector.active():
                self.reconnector.cancel()
            self.reconnector = None
            self.retry = 0

    def _error_handler(self, failure, tag=None):
        exception = failure.value
        msg = failure.getErrorMessage()
        if isinstance(exception, web_error.Error):
            prefix = (tag + " ") if tag is not None else ""
            status = int(exception.status)
            if status == 409:
                raise ConflictError("%s%s" % (prefix, msg))
            elif status == 404:
                raise NotFoundError("%s%s" % (prefix, msg))
            else:
                self.error('%s%s' % (prefix, exception.response))
                raise NotImplementedError(
                    'Behaviour for response code %d not defined yet, FIXME!' %
                    status)
        elif failure.check(error.ConnectionRefusedError):
            self._on_disconnected()
            self.reconnect()
            raise NotConnectedError("Database connection refused.")
        else:
            failure.raiseException()
