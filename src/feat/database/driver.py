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
import types
import operator
from urllib import urlencode, quote

from zope.interface import implements
from twisted.internet import error as tw_error, task
from twisted.python import failure
from twisted.protocols import basic
from twisted.web.http import _DataLoss as DataLoss


from feat.database.client import Connection, ChangeListener
from feat.common import log, defer, time, error, enum, container
from feat.agencies import common
from feat.web import http, httpclient, auth, security
from feat import hacks

json = hacks.import_json()

from feat.database.interface import IDatabaseDriver, IDbConnectionFactory
from feat.database.interface import NotFoundError, NotConnectedError
from feat.database.interface import ConflictError, IViewFactory, DatabaseError
from feat.database.interface import IAttachmentPrivate


DEFAULT_DB_HOST = "localhost"
DEFAULT_DB_PORT = 5985
DEFAULT_DB_NAME = "feat"

BOUNDARY = '32c90c040f034b15959861e58b8ec35d'


class Methods(http.Methods):
    '''
    This is override to define a non-standard extension used by couchdb (COPY).
    '''

    COPY = 6


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
                              self._db.couchdb.get, url)

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
                self._filter.notified(doc_id, line['rev'], deleted)
        else:
            self.info('Bizare notification received from CouchDB: %r', change)

    def connectionLost(self, reason):
        self._changes = None
        if reason.check(NotFoundError):
            return reason
        self._db.connectionLost(reason)


class CouchDB(httpclient.ConnectionPool):

    log_category = 'couchdb-connection'

    def __init__(self, host, port, username=None, password=None,
                 https=False, maximum_connections=2, logger=None):
        if username is not None and password is not None:
            a = auth.BasicHTTPCredentials(username, password)
            self._auth_header = a.header_value
        else:
            self._auth_header = None
        if https:
            sp = security.ClientPolicy(security.ClientContextFactory())
        else:
            sp = None

        httpclient.ConnectionPool.__init__(
            self, host, port,
            maximum_connections=maximum_connections,
            security_policy=sp,
            logger=logger,
            enable_pipelineing=False)

    def get(self, url, headers=dict(), **extra):
        self._set_auth(headers)
        headers.setdefault('accept', "application/json")
        return self.request(http.Methods.GET, url, headers=headers, **extra)

    def copy(self, url, headers, **extra):
        self._set_auth(headers)
        headers.setdefault('accept', "application/json")
        return self.request(Methods.COPY, url, headers=headers, **extra)

    def put(self, url, body=None, headers=dict(), **extra):
        self._set_auth(headers)
        headers.setdefault('accept', "application/json")
        headers.setdefault('content-type', "application/json")
        return self.request(http.Methods.PUT, url,
                            body=body, headers=headers, **extra)

    def post(self, url, body=None, headers=dict(), **extra):
        self._set_auth(headers)
        headers.setdefault('accept', "application/json")
        headers.setdefault('content-type', "application/json")
        return self.request(http.Methods.POST, url,
                            body=body, headers=headers, **extra)

    def delete(self, url, headers=dict(), **extra):
        self._set_auth(headers)
        headers.setdefault('accept', "application/json")
        return self.request(http.Methods.DELETE, url, headers=headers,
                            **extra)

    def _set_auth(self, headers):
        if self._auth_header:
            headers['authorization'] = self._auth_header
        return headers


class Database(common.ConnectionManager, log.LogProxy, ChangeListener):

    implements(IDbConnectionFactory, IDatabaseDriver)

    log_category = "database"

    LoopingCall = task.LoopingCall
    # we should take roughly 10MB of cache
    DESIRED_CACHE_SIZE = 10 * 1024 * 1024

    def __init__(self, host, port, db_name, username=None, password=None,
                 https=False):
        common.ConnectionManager.__init__(self)
        log.LogProxy.__init__(self, log.get_default() or log.FluLogKeeper())
        ChangeListener.__init__(self, self)

        self.couchdb = None
        self.db_name = None
        self.version = None
        self.host = None
        self.port = None
        self.https = None
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
        self._cache = Cache(desired_size=self.DESIRED_CACHE_SIZE)

        self._configure(host, port, db_name, username, password,
                        https)

    def reconfigure(self, host, port, name, username=None, password=None,
                    https=False):
        self._configure(host, port, name, username, password, https)

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

    def open_doc(self, doc_id, **extra):
        url = '/%s/%s' % (self.db_name, quote(doc_id.encode('utf-8')))
        if extra:
            url += '?'
            # this is necessary, because otherwise we would pass True or False
            # to couchdb, and it requires smallcase
            for k, v in extra.iteritems():
                if isinstance(v, types.BooleanType):
                    extra[k] = str(v).lower()
            url += urlencode(extra)
        return self.couchdb_call(self.couchdb.get, url)

    def copy_doc(self, doc_id, destination_id, rev=None):
        url = '/%s/%s' % (self.db_name, quote(doc_id.encode('utf-8')))
        dest = quote(destination_id.encode('utf-8'))
        if rev:
            dest += '?rev=' + quote(rev.encode('utf-8'))
        headers = {'Destination': dest}
        return self.couchdb_call(self.couchdb.copy, url,
                                 headers=headers)

    @defer.inlineCallbacks
    def save_doc(self, doc, doc_id=None, following_attachments=None,
                 db_name=None):
        db_name = db_name or self.db_name
        if doc_id:
            url = '/%s/%s' % (db_name, quote(doc_id.encode('utf-8')))
            method = self.couchdb.put
            force_json = False
        else:
            url = '/%s/' % (db_name, )
            method = self.couchdb.post
            force_json = True
        version = yield self.get_version()

        # This turns off using multipart requests for now
        force_json = True

        if not following_attachments:
            r = yield self.couchdb_call(method, url, doc)
            defer.returnValue(r)
        elif version >= (1, 1, 2) and not force_json:
            ### FIXME: This part is disabled because force_json is always True
            ###        This is because of the problems with occasional 500
            ###        responses with "reason": "function_clause"
            parts = ["\r\ncontent-type: application/json\r\n\r\n%s\r\n" %
                     (doc, )]
            following = following_attachments.items()
            following.sort(key=operator.itemgetter(0))
            for _, attachment in following:
                parts.append("\r\n\r\n%s\r\n" % (attachment.get_body(), ))
            separator = "--" + BOUNDARY
            body = separator + separator.join(parts) + separator + "--"
            content_type = 'multipart/related;boundary=%s' % (BOUNDARY, )
            headers = {'content-type': content_type}
            r = yield self.couchdb_call(
                method, url, body, headers=headers)
            defer.returnValue(r)
        else:
            # Updating documents with multipart/related doesnt work
            # in couchdb version prior to 1.1.2.
            # Also multipart request cannot be used when creating new documents
            unserialized = json.loads(doc)
            for name, body in unserialized['_attachments'].items():
                if body.get('follows'):
                    del unserialized['_attachments'][name]
            doc = json.dumps(unserialized)

            r = yield self.couchdb_call(method, url, doc)
            for attachment in following_attachments.itervalues():
                r = yield self.save_attachment(r['id'], r['rev'], attachment)
            defer.returnValue(r)

    def delete_doc(self, doc_id, revision):
        url = "/%s/%s?%s" % (self.db_name, quote(doc_id.encode('utf-8')),
                             urlencode({'rev': revision.encode('utf-8')}))

        return self.couchdb_call(self.couchdb.delete, url)

    def create_db(self):
        url = '/%s/' % (self.db_name, )
        return self.couchdb_call(self.couchdb.put, url)

    def delete_db(self):
        url = '/%s/' % (self.db_name, )
        return self.couchdb_call(self.couchdb.delete, url)

    def replicate(self, source, target, **options):
        url = '/_replicate'
        params = dict(source=source, target=target)
        params.update(options)
        body = json.dumps(params)
        return self.couchdb_call(self.couchdb.post, url, body)

    def disconnect(self):
        self._cancel_reconnector()
        self.couchdb.disconnect()
        self.disconnected = True

    # listen_chagnes from ChangeListener

    # cancel_listener from ChangeListener

    def query_view(self, factory, post_process=None, cache_id_suffix='',
                   if_modified_since=None, **options):
        factory = IViewFactory(factory)

        url = "/%s/_design/%s/_view/%s" % (self.db_name,
                                           quote(str(factory.design_doc_id)),
                                           quote(str(factory.name)))
        cache_id = None
        if 'keys' in options:
            keys = options.pop("keys")
            body = json.dumps({"keys": keys})
            cache_id = "%s#%s" % (url, hash(tuple(sorted(keys))))
        else:
            body = None

        if options:
            encoded = urlencode(dict((k, json.dumps(v))
                                     for k, v in options.iteritems()))
            url += '?' + encoded

        if cache_id is None:
            cache_id = url
        cache_id += cache_id_suffix

        if post_process:
            parser = (parse_response, parse_view_result, post_process)
        else:
            parser = (parse_response, parse_view_result)

        if body:
            return self.couchdb_call(self.couchdb.post, url, body=body,
                                     cache_id=cache_id, parser=parser,
                                     if_modified_since=if_modified_since)
        else:
            return self.couchdb_call(self.couchdb.get, url,
                                     cache_id=cache_id, parser=parser,
                                     if_modified_since=if_modified_since)

    def save_attachment(self, doc_id, revision, attachment):
        attachment = IAttachmentPrivate(attachment)
        uri = ('/%s/%s/%s?rev=%s' %
               (self.db_name, quote(doc_id.encode('utf-8')),
                quote(attachment.name), revision.encode('utf-8')))
        headers = {'content-type': attachment.content_type}
        body = attachment.get_body()
        if isinstance(body, unicode):
            body = body.encode('utf-8')
        d = self.couchdb_call(self.couchdb.put, uri, body,
                              headers=headers)
        return d

    def get_attachment(self, doc_id, name):
        uri = ('/%s/%s/%s' % (self.db_name,
                              quote(doc_id.encode('utf-8')),
                              quote(name.encode('utf-8'))))
        headers = {'accept': '*'}
        return self.couchdb_call(self.couchdb.get, uri,
                                 parser=parse_binary,
                                 headers=headers,
                                 cache_id=uri)

    def get_update_seq(self):
        url = "/%s/" % (self.db_name, )
        d = self.couchdb_call(self.couchdb.get, url)
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
        return self.couchdb_call(self.couchdb.get, url)

    def bulk_get(self, doc_ids):
        url = '/%s/_all_docs?include_docs=true' % (self.db_name, )
        body = dict(keys=doc_ids)
        cache_id = "%s#%s" % (url, hash(tuple(doc_ids)))
        return self.couchdb_call(self.couchdb.post,
                                 url, json.dumps(body), cache_id=cache_id)

    def get_version(self):
        if self.version:
            return defer.succeed(self.version)
        else:
            d = self.couchdb_call(self.couchdb.get, '/')
            d.addCallback(self._set_version)
            return d

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
                          self.couchdb.get, '/')
            d.addCallback(self._set_version)
            d.addCallback(defer.drop_param, self._setup_notifiers)
            d.addErrback(failure.Failure.trap, NotConnectedError)
            d.addErrback(failure.Failure.trap, defer.CancelledError)
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

    ### private

    def couchdb_call(self, method, url, *args, **kwargs):
        cache_id = kwargs.pop('cache_id', None)
        parser = kwargs.pop('parser', parse_response)
        if_modified_since = kwargs.pop('if_modified_since', None)

        tag = "%s on %s" % (method.__name__.upper(), url)
        entry = None

        if cache_id:
            entry = self._cache.get_url(cache_id)
            if entry and entry.state == EntryState.waiting:
                # There is ongoing request to this URL, just wait
                # for the result.
                return entry.wait()

            if not entry:
                # Its the first request to this request or its not
                # a cacheable entity.

                entry = CacheEntry(tag, parser)
                self._cache[cache_id] = entry

            if entry.etag:

                if if_modified_since and if_modified_since < entry.fresh_at:
                    # just reuse the cached response if the response was
                    # cached latere than the provided time
                    return entry.wait()

                entry.state = EntryState.waiting

                # We have cached entry with ETag header,
                # there is a big chance that its fresh.
                # Below use the normal HTTP way of revalidating the cache.
                kwargs.setdefault('headers', dict())
                kwargs['headers']['If-None-Match'] = entry.etag

        d = method(url, *args, **kwargs)
        d.addCallback(defer.bridge_param, self._on_connected)
        if entry:
            d.addCallback(defer.keep_param, self._cache.freshen_entries)
            d.addBoth(defer.keep_param, entry.got_response)
            d.addErrback(self._error_handler)
            return entry.wait()
        else:
            d.addCallbacks(apply_parsers, self._error_handler,
                           callbackArgs=(parser, tag, ))
            return d

    def _configure(self, host, port, name, username, password, https):
        self._cancel_reconnector()
        self.host, self.port = host, port
        self.username, self.password = username, password
        self.https = https
        self.couchdb = CouchDB(host, port, username, password, logger=self,
                               https=https)
        self.db_name = name
        self.disconnected = False

        self._pending_notifications.clear()
        self._document_locks.clear()

        self.reconnect()

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
        self.version = tuple(map(int, response.get('version', '').split('.')))
        # # This is not handled well in 1.2.2 either. After 409 response
        # # the connection is closed without the Connection: close header.
        # # This should be reenabled when either couchdb fixes it, or our
        # # client handles this case.
        # self.couchdb.enable_pipelineing(self.version >= (1, 2, 0))
        self.couchdb.enable_pipelineing(False)

        return self.version

    def _cancel_reconnector(self):
        if self.reconnector:
            self.debug("Reconnected to couchdb.")
            if self.reconnector.active():
                self.reconnector.cancel()
            self.reconnector = None
            self.retry = 0

    def _error_handler(self, failure):
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


class EntryState(enum.Enum):
    '''
    waiting - request is in progress
    ready - the data is ready and cached
    invalid - the entry should be removed from the cache
    '''

    waiting, ready, invalid = range(3)


class CacheEntry(object):

    __slots__ = (
        '_parsed', '_parser',
        '_waiting', 'cached_at', 'etag', 'fresh_at', 'last_accessed_at',
        'num_accessed', 'size', 'state', 'tag')

    def __init__(self, tag, parser):
        # tag is used for error handling
        self.tag = tag
        self.state = EntryState.waiting
        self.etag = None

        # private attributes
        self._waiting = list()
        self._parsed = None
        # parser is a callable taking parameters:
        # - response object
        # - tag C{str}
        # It returns failure.Failure() instance or any object which will be
        # considered the result of the request (and will be cached)

        if not (callable(parser) or isinstance(parser, tuple)):
            raise ValueError("parser needs to be a callable or tuple of "
                             "callables, %r passed" % (parser, ))
        self._parser = parser

        # public statistics
        self.cached_at = None
        self.fresh_at = None
        self.last_accessed_at = None
        self.num_accessed = 0
        self.size = None

    def wait(self, ctime=None):
        self.last_accessed_at = ctime or time.time()
        self.num_accessed += 1

        if self.state == EntryState.ready:
            return defer.succeed(self._parsed)
        else:
            d = defer.Deferred()
            self._waiting.append(d)
            return d

    def got_response(self, response, ctime=None):
        ctime = ctime or time.time()
        if isinstance(response, failure.Failure):
            self.size = None
            self._parsed = response
            self.state = EntryState.invalid

        elif response.status == 304:
            self.state = EntryState.ready
            self.fresh_at = ctime
        else:
            self._parsed = apply_parsers(response, self._parser, self.tag)
            if isinstance(self._parsed, failure.Failure):
                self.state = EntryState.invalid
            else:
                self.state = EntryState.ready
                self.size = len(response.body)

                if not self.cached_at:
                    self.cached_at = ctime
                    self.fresh_at = ctime
                if response.headers.get('etag'):
                    self.etag = response.headers.get('etag')
                else:
                    self.state = EntryState.invalid

        # trigger waiting Deferreds
        waiting = self._waiting
        self._waiting = list()

        for d in waiting:
            d.callback(self._parsed)

    def __str__(self):
        return "<Entry, state: %s, tag: %s>" % (self.state.name, self.tag)


class Cache(dict):
    '''
    url -> CacheEntry
    '''

    DEFAULT_DESIRED_SIZE = 10 * 1024 * 1024
    OPERATIONS_PER_CLEANUP = 500

    def __init__(self, desired_size=None):
        super(Cache, self).__init__()
        self.desired_size = desired_size or self.DEFAULT_DESIRED_SIZE
        self.average_size = container.RunningAverage(0)
        self.average_cleanup_time = container.RunningAverage(0)
        self.last_cleanup = None
        self._operation = 0

    def get_url(self, identifier):
        self._bump_counter()
        if identifier in self and self[identifier].state != EntryState.invalid:
            return self[identifier]

    def __setitem__(self, key, value):
        super(Cache, self).__setitem__(key, value)
        self._bump_counter()

    def _bump_counter(self):
        self._operation += 1
        if self._operation % self.OPERATIONS_PER_CLEANUP == 0:
            self.cleanup()

    def cleanup(self, ctime=None):
        '''
        This method is called iteratively by the connection owning it.
        Its job is to control the size of cache and remove old entries.
        '''
        ctime = ctime or time.time()
        if self.last_cleanup:
            self.average_cleanup_time.add_point(ctime - self.last_cleanup)
        self.last_cleanup = ctime

        log.debug('couchdb', "Running cache cleanup().")
        # first remove already invalidated entries, used this iteration to
        # build up the map of usage
        expire = list()

        # [(num_accessed / time_in_cache, size, ident)]
        usage = list()

        actual_size = 0

        for ident, entry in self.iteritems():
            if entry.state is EntryState.invalid:
                expire.append(ident)
                continue
            elif entry.state is EntryState.waiting:
                continue
            else: # EntryState.ready
                actual_size += entry.size
                time_in_cache = max([ctime - entry.cached_at, 1])
                usage.append((
                    float(entry.num_accessed) / time_in_cache,
                    -entry.size,
                    ident))

        self.average_size.add_point(actual_size)

        if self.average_size.get_value() > 3 * self.desired_size:
            log.warning("couchdb", "The average size of Cache is %.2f times "
                        "bigger than the desired size of: %s. It might be "
                        "a good idea to rethink the caching strategy.",
                        self.average_size.get_value() / self.desired_size,
                        self.desired_size)

        if actual_size > self.desired_size:
            log.debug('couchdb', "I will have to cleanup some data, "
                      "the actual size is: %s, the desired limit is %s.",
                      actual_size, self.desired_size)
            # The usage list is sorted in order of things I will
            # be removing first. The important factor is "density" of usages
            # in time.
            usage.sort()
            size_to_delete = 0
            num_to_delete = 0
            while (len(usage) > 1 and
                   actual_size - size_to_delete > self.desired_size):
                _, negative_size, ident = usage.pop(0)
                size_to_delete += -negative_size
                num_to_delete += 1
                expire.append(ident)
            log.debug('couchdb', "I will remove %d entries from cache of the "
                      "size of %s to compensate the size.",
                      num_to_delete, size_to_delete)

        for ident in expire:
            del self[ident]

    def get_size(self):
        return sum([x.size for x in self.itervalues()])

    def freshen_entries(self, response):
        etag = response.headers.get('etag')
        if response.status == 304 and etag:
            ctime = time.time()
            for entry in self.itervalues():
                if entry.etag == etag:
                    entry.fresh_at = ctime


def apply_parsers(response, parsers, tag):
    if callable(parsers):
        return parsers(response, tag)
    for parser in parsers:
        if isinstance(parser, (list, tuple)):
            response = parser[0](response, tag, *parser[1:])
        else:
            response = parser(response, tag)
        if isinstance(response, failure.Failure):
            break
    return response


def parse_response(response, tag):
    if response.status < 300:
        if (response.headers.get('content-type') == 'application/json'):
            try:
                return json.loads(response.body)
            except ValueError:
                log.error('couchdb',
                    "Could not parse json data from couchdb. Data: %r",
                    response.body)
                return failure.Failure(DatabaseError("Json parse error"))
        else:
            return response.body
    else:
        msg = ("%s gave %s status with body: %s"
               % (tag, response.status.name, response.body))
        if response.status == http.Status.NOT_FOUND:
            return failure.Failure(NotFoundError(msg))
        elif response.status == http.Status.CONFLICT:
            return failure.Failure(ConflictError(msg))
        else:
            return failure.Failure(DatabaseError(msg))


def parse_binary(response, tag):
    if response.status < 300:
        return response.body
    else:
        msg = ("%s gave %s status with body: %s"
               % (tag, response.status.name, response.body))
        if response.status == http.Status.NOT_FOUND:
            return failure.Failure(NotFoundError(msg))
        else:
            return failure.Failure(DatabaseError(msg))


def parse_view_result(resp, tag):
    if "rows" not in resp:
        msg = ("The response didn't have the \"rows\" key.\n%r" %
               (resp, ))
        return failure.Failure(DatabaseError(msg))

    result = list()

    for row in resp["rows"]:
        if "id" in row:
            if "doc" in row:
                # querying with include_docs=True
                r = (row["key"], row["value"], row["id"], row["doc"])
                result.append(r)
            else:
                # querying without reduce
                result.append((row["key"], row["value"], row["id"]))
        else:
            # querying with reduce
            result.append((row["key"], row["value"]))

    return result
