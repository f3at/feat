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
from urllib import urlencode, quote

from zope.interface import implements
from twisted.internet import error as tw_error
from twisted.python import failure
from twisted.protocols import basic
from twisted.web.http import _DataLoss as DataLoss

from feat.database.client import Connection, ChangeListener
from feat.common import log, defer, time, error
from feat.agencies import common
from feat.web import http, httpclient
from feat import hacks

json = hacks.import_json()

from feat.database.interface import IDatabaseDriver, IDbConnectionFactory
from feat.database.interface import NotFoundError, NotConnectedError
from feat.database.interface import ConflictError, IViewFactory, DatabaseError
from feat.database.interface import IAttachmentPrivate


DEFAULT_DB_HOST = "localhost"
DEFAULT_DB_PORT = 5985
DEFAULT_DB_NAME = "feat"


class ChangeReceiver(basic.LineReceiver):

    delimiter = '\n'

    def __init__(self, notifier):
        self._notifier = notifier
        self._deferred = defer.Deferred()

        self.status = None
        self.headers = {}
        self.length = None
        self.stopping = False

    def get_result(self):
        return self._deferred

    def connectionMade(self):
        d = self._deferred
        self._deferred = None
        if self.status == 200:
            d.callback(self)
        elif self.status == 404:
            self.stopping = True
            f = failure.Failure(NotFoundError(self._notifier.name))
            f.cleanFailure()
            d.errback(f)
        else:
            self.stopping = True
            msg = ("Calling change notifier: %s gave %s status code" %
                   (self._notifier.name, int(self.status)))
            f = failure.Failure(DatabaseError(msg))
            f.cleanFailure()
            d.errback(f)

    def lineReceived(self, line):
        if not line:
            return

        change = json.loads(line)

        if not 'id' in change:
            return

        self._notifier.changed(change)

    def stop(self):
        if self._deferred:
            self._deferred.cancel()
            self._deferred = None
        else:
            self.stopping = True
            self.transport.loseConnection()

    def connectionLost(self, reason=None):
        if self.stopping:
            return
        if not reason or reason.check(DataLoss):
            reason = failure.Failure(
                tw_error.ConnectionLost("Couchdb closed connection"))
            reason.cleanFailure()
        if self._deferred:
            d = self._deferred
            self._deferred = None
            d.errback(reason)
        else:
            self._notifier.connectionLost(reason)


class Notifier(object):

    def __init__(self, db, filter_):
        self._db = db
        self._filter = filter_
        self.name = self._filter.name
        self._params = None
        self._changes = None

    def setup(self):
        new_params = self._filter.extract_params()
        if (self._params is not None and
            new_params == self._params and
            self._changes is not None):
            return defer.succeed(None)

        self._params = new_params

        if self._changes is not None:
            self._changes.stop()
            self._changes = None


        d = defer.succeed(None)
        if new_params is not None:
            self._changes = ChangeReceiver(self)
            d.addCallback(defer.drop_param, self._db.wait_connected)

            query = dict(new_params)
            query['feed'] = 'continuous'
            query['heartbeat'] = 1000
            if 'since' not in query:
                url = '/%s/' % (self._db.db_name, )
                d.addCallback(defer.drop_param, self._db.couchdb_call,
                              'infoDB', self._db.couchdb.get, url)

                def set_since(resp):
                    query['since'] = resp['update_seq']

                d.addCallback(set_since)

            def request_changes(decoder, query):
                url = '/%s/_changes?%s' % (self._db.db_name, urlencode(query))
                return self._db.couchdb.get(url, decoder=decoder,
                                            outside_of_the_pool=True,
                                            headers={'connection': 'close'})

            d.addCallback(defer.drop_param, request_changes, self._changes,
                          query)
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
        self._changes = None
        if reason.check(NotFoundError):
            return reason
        self._db.connectionLost(reason)


class CouchDB(httpclient.ConnectionPool):

    log_category = 'couchdb-connection'

    def __init__(self, host, port, maximum_connections=2, logger=None):
        httpclient.ConnectionPool.__init__(
            self, host, port,
            maximum_connections=maximum_connections,
            logger=logger)

    def get(self, url, headers=dict(), **extra):
        headers.setdefault('accept', "application/json")
        return self.request(http.Methods.GET, url, headers=headers, **extra)

    def put(self, url, body='', headers=dict(), **extra):
        headers.setdefault('accept', "application/json")
        headers.setdefault('content-type', "application/json")
        return self.request(http.Methods.PUT, url, body=body.encode('utf8'),
                            headers=headers, **extra)

    def post(self, url, body='', headers=dict(), **extra):
        headers.setdefault('accept', "application/json")
        headers.setdefault('content-type', "application/json")
        return self.request(http.Methods.POST, url, body=body.encode('utf8'),
                            headers=headers, **extra)

    def delete(self, url, headers=dict(), **extra):
        headers.setdefault('accept', "application/json")
        return self.request(http.Methods.DELETE, url, headers=headers,
                            **extra)


class Database(common.ConnectionManager, log.LogProxy, ChangeListener):

    implements(IDbConnectionFactory, IDatabaseDriver)

    log_category = "database"

    def __init__(self, host, port, db_name):
        common.ConnectionManager.__init__(self)
        log.LogProxy.__init__(self, log.get_default() or log.FluLogKeeper())
        ChangeListener.__init__(self, self)

        self.couchdb = None
        self.db_name = None
        self.version = None
        self.host = None
        self.port = None
        # name -> Notifier
        self.notifiers = dict()
        # this flag is prevents reconnector from being spawned
        self.disconnected = False

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
        url = '/%s/%s' % (self.db_name, quote(doc_id.encode('utf-8')))
        return self.couchdb_call(doc_id, self.couchdb.get, url)

    def save_doc(self, doc, doc_id=None):
        if doc_id:
            url = '/%s/%s' % (self.db_name, quote(doc_id.encode('utf-8')))
            method = self.couchdb.put
        else:
            url = '/%s/' % (self.db_name, )
            method = self.couchdb.post
        return self._lock_document(doc_id, self.couchdb_call, doc_id,
                                   method, url, doc)

    def delete_doc(self, doc_id, revision):
        url = "/%s/%s?%s" % (self.db_name, quote(doc_id.encode('utf-8')),
                             urlencode({'rev': revision.encode('utf-8')}))

        return self._lock_document(doc_id, self.couchdb_call, doc_id,
                                   self.couchdb.delete, url)

    def create_db(self):
        url = '/%s/' % (self.db_name, )
        return self.couchdb_call(self.db_name, self.couchdb.put, url)

    def delete_db(self):
        url = '/%s/' % (self.db_name, )
        return self.couchdb_call(self.db_name, self.couchdb.detele, url)

    def replicate(self, source, target, **options):
        url = '/_replicate'
        params = dict(source=source, target=target)
        params.update(options)
        body = json.dumps(params)
        return self.couchdb_call('replicate', self.couchdb.post, url, body)

    def disconnect(self):
        self._cancel_reconnector()
        self.couchdb.disconnect()
        self.disconnected = True

    # listen_chagnes from ChangeListener

    # cancel_listener from ChangeListener

    def query_view(self, factory, **options):
        factory = IViewFactory(factory)

        url = "/%s/_design/%s/_view/%s" % (self.db_name,
                                           quote(str(factory.design_doc_id)),
                                           quote(str(factory.name)))
        if 'keys' in options:
            body = json.dumps({"keys": options.pop("keys")})
        else:
            body = None
        if options:
            encoded = urlencode(dict((k, json.dumps(v))
                                     for k, v in options.iteritems()))
            url += '?' + encoded
        if body:
            d = self.couchdb_call(factory.design_doc_id, self.couchdb.post,
                                  url, body=body)
        else:
            d = self.couchdb_call(factory.design_doc_id, self.couchdb.get, url)
        d.addCallback(self._parse_view_result)
        return d

    def save_attachment(self, doc_id, revision, attachment):
        attachment = IAttachmentPrivate(attachment)
        uri = ('/%s/%s/%s?rev=%s' %
               (self.db_name, quote(doc_id.encode('utf-8')),
                quote(attachment.name), revision.encode('utf-8')))
        headers = {'content-type': attachment.content_type}
        body = attachment.get_body()
        if isinstance(body, unicode):
            body = body.encode('utf-8')
        d = self._lock_document(doc_id, self.couchdb_call, doc_id,
                                self.couchdb.put, uri, body, headers=headers)
        return d

    def get_attachment(self, doc_id, name):
        uri = ('/%s/%s/%s' % (self.db_name,
                              quote(doc_id.encode('utf-8')),
                              quote(name.encode('utf-8'))))
        headers = {'accept': '*'}
        return self.couchdb_call(doc_id, self.couchdb.get, uri,
                                 headers=headers)

    def get_update_seq(self):
        url = "/%s/" % (self.db_name, )
        d = self.couchdb_call('update_seq', self.couchdb.get, url)
        d.addCallback(lambda x: x['update_seq'])
        return d

    def get_changes(self, filter_, limit=None, since=0):
        params = dict(since=since)
        if limit is not None:
            params['limit'] = limit
        if filter_ is not None:
            params['filter'] = str('%s/%s' % (filter_.view.design_doc_id,
                                              filter_.view.name))
        url = str('/%s/_changes?%s' % (self.db_name, urlencode(params)))
        return self.couchdb_call('get_changes', self.couchdb.get, url)

    def bulk_get(self, doc_ids):
        url = '/%s/_all_docs?include_docs=true' % (self.db_name, )
        return self.couchdb_call('bulk_get', self.couchdb.post,
                                 url, json.dumps(dict(keys=doc_ids)))

    ### public ###

    def reconnect(self):
        # ping database to figure trigger changing state to connected
        if self.is_connected():
            return defer.succeed(self)
        if self.disconnected:
            return

        if self.reconnector is None or not self.reconnector.active():
            self.retry += 1
            wait = min(2**(self.retry - 1), 300)
            if self.retry > 1:
                self.debug('CouchDB refused connection for %d time. '
                           'This indicates misconfiguration or temporary '
                           'network problem. Will try to reconnect in '
                           '%d seconds.', self.retry, wait)
            d = defer.Deferred()
            d.addCallback(defer.drop_param, self.couchdb_call,
                          'reconnect', self.couchdb.get, '/')
            d.addCallback(self._set_version)
            d.addCallback(defer.drop_param, self._setup_notifiers)
            d.addErrback(failure.Failure.trap, NotConnectedError)
            self.reconnector = time.callLater(wait, d.callback, None)
            return d
        else:
            return self.wait_connected()

    def connectionLost(self, reason):
        if reason.check(tw_error.ConnectionDone):
            # expected just pass
            return
        elif reason.check(tw_error.ConnectionLost):
            self.debug("CouchDB closed the notification listener. This might "
                       "indicate misconfiguration. Take a look at it.")
            self._on_disconnected()
            self.reconnect()
            return
        elif reason.check(tw_error.ConnectionRefusedError):
            self.reconnect()
            return
        else:
            # FIXME handle disconnection when network is down
            self._on_disconnected()
            error.handle_failure(self, reason,
                                 'Connection to couchdb lost with '
                                 'unusual reason.')
            self.reconnect()

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

    def couchdb_call(self, tag, method, *args, **kwargs):
        d = method(*args, **kwargs)
        d.addCallbacks(self._couchdb_cb, self._error_handler,
                       callbackArgs=(tag, ), errbackArgs=(tag, ))
        return d

    def _couchdb_cb(self, response, tag):
        self._on_connected()
        if response.status < 400:
            if response.headers.get('content-type') == 'application/json':
                try:
                    return json.loads(response.body)
                except ValueError:
                    self.error(
                        "Could not parse json data from couchdb. Data: %r",
                        response.body)
                    raise DatabaseError("Json parse error")
            else:
                return response.body
        else:
            msg = response.body
            if tag:
                msg = tag + " " + msg
            if response.status == http.Status.NOT_FOUND:
                raise NotFoundError(msg)
            elif response.status == http.Status.CONFLICT:
                raise ConflictError(msg)
            else:
                raise DatabaseError(str(int(response.status)) + ": " + msg)

    def _configure(self, host, port, name):
        self._cancel_reconnector()
        self.host, self.port = host, port
        self.couchdb = CouchDB(host, port, logger=self)
        self.db_name = name
        self.disconnected = False

        self._pending_notifications.clear()
        self._document_locks.clear()

        self.reconnect()

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

    def _set_version(self, response):
        self.version = response.get('version')

    def _cancel_reconnector(self):
        if self.reconnector:
            self.debug("Reconnected to couchdb.")
            if self.reconnector.active():
                self.reconnector.cancel()
            self.reconnector = None
            self.retry = 0

    def _error_handler(self, failure, tag=None):
        if failure.check(tw_error.ConnectionRefusedError):
            self._on_disconnected()
            self.reconnect()
            raise NotConnectedError("Database connection refused.")
        elif (failure.check(httpclient.RequestError) and
              failure.value.cause and
              isinstance(failure.value.cause, tw_error.ConnectionDone)):
            self._on_disconnected()
            self.reconnect()
            raise NotConnectedError("Connection to the database was lost.")
        else:
            failure.raiseException()
