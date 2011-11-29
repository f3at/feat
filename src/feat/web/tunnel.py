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

import random

from zope.interface import Interface, implements

import feat
from feat.common import defer, error, time
from feat.common.serialization import json
from feat.web import http, security, base, httpserver, httpclient

DEFAULT_REQUEST_TIMEOUT = 5*60
DEFAULT_RESPONSE_TIMEOUT = 5*60+1

FEAT_IDENT = "FeatTunnel"


class TunnelError(error.FeatError):
    pass


class ITunnelDispatcher(Interface):

    def dispatch(uri, data):
        """Dispatches a message."""


class Tunnel(base.RangeServer):

    implements(httpserver.IHTTPServerOwner)

    log_category = "http-tunnel"

    request_timeout = DEFAULT_REQUEST_TIMEOUT
    response_timeout = DEFAULT_RESPONSE_TIMEOUT
    idle_timeout = None # Default value

    # Taken from flumotion reconnectin client factory
    max_delay = 600
    initial_delay = 1.0
    factor = 2.7182818284590451
    jitter = 0.11962656472

    def __init__(self, log_keeper, port_range, dispatcher,
                 public_host=None, version=None, registry=None,
                 server_security_policy=None,
                 client_security_policy=None, max_delay=None):
        base.RangeServer.__init__(self, port_range,
                                  hostname=public_host,
                                  security_policy=server_security_policy,
                                  log_keeper=log_keeper)

        self._dispatcher = ITunnelDispatcher(dispatcher)

        ### protected attributes, used by Peer and/or Request ###
        ver = version if version is not None else feat.version
        self._version = int(ver)
        self._registry = registry

        self._client_security = security.ensure_policy(client_security_policy)

        self._uri = None

        self._retries = {} # {PEER_KEY: IDelayedCall}
        self._delays = {} # {PEER_KEY: DELAY}
        self._quarantined = set([]) # set([PEER_KEY])
        self._pendings = {} # {PEER_KEY: [(DEFERRED, PATH, DATA, EXPIRATION)]}
        self._peers = {} # {KEY: Peer}

        self._max_delay = max_delay or type(self).max_delay

    @property
    def version(self):
        return self._version

    @property
    def uri(self):
        return self._uri

    def is_idle(self):
        if self._retries:
            return False
        if self._pendings:
            return False
        if self.factory is not None and not self.factory.is_idle():
            return False
        for peer in self._peers.itervalues():
            if not peer.is_idle():
                return False
        return True

    def get_peers(self):
        return [self._key2url(k) for k in self._peers]

    def post(self, url, data, expiration=None):
        scheme, host, port, path, query = http.parse(url)
        location = http.compose(path, query)

        key = (scheme, host, port)

        now = time.time()
        exp = expiration + now if expiration is not None else None

        if key in self._quarantined:
            return self._add_pending(key, path, data, exp)

        if key not in self._peers:
            d = self._add_pending(key, path, data, exp)
            self._connect(key)
            return d

        d = defer.Deferred()
        self._post(key, location, data, exp, now, d)
        return d

    def disconnect(self):
        self._cancel_retries()
        for peer in self._peers.values():
            peer.disconnect()
        base.RangeServer.disconnect(self)

    ### httpserver.IHTTPServerOwner ###

    def onServerConnectionMade(self, channel):
        pass

    def onServerConnectionLost(self, channel, reason):
        pass

    ### overridden ###

    def _create_factory(self):
        factory = httpserver.Factory(self, self)
        factory.request_factory_class = RequestFactory
        return factory

    def _on_listening(self):
        self._uri = "http://%s:%d/" % (self.hostname, self.port)

    def _on_stopped(self):
        self._uri = None

    ### protected ##

    def _remove_peer(self, key):
        del self._peers[key]
        if key in self._pendings:
            self._schedule_retry(key)

    def _dispatch(self, uri, data):
        self._dispatcher.dispatch(uri, data)

    ### private ###

    def _add_pending(self, key, location, data, expiration, d=None):
        if key not in self._pendings:
            self._pendings[key] = []
        d = d if d is not None else defer.Deferred()
        record = (d, location, data, expiration)
        self._pendings[key].append(record)
        return d

    def _connect(self, key):
        self.log("Connecting to %s", self._key2url(key))

        # Quarantined until connected
        self._quarantined.add(key)
        peer = Peer(self, key, self._client_security)
        self._peers[key] = peer

        if self._version:
            d = peer.head("/")
            args = (key, )
            d.addCallbacks(self._got_root_headers, self._handcheck_failed,
                           callbackArgs=args, errbackArgs=args)
            return d

    def _got_root_headers(self, response, key):
        self._reset_retry(key)
        self._quarantined.remove(key)
        return self._post_pendings(key)

    def _handcheck_failed(self, failure, key):
        error.handle_failure(self, failure, "Failure connecting to tunnel "
                             " %s:" % self._key2url(key))
        self._schedule_retry(key)

    def _post(self, key, location, data, expiration, curr_time, deferred):
        if expiration and expiration <= curr_time:
            deferred.callback(False)
            return

        d = self._peers[key].post(location, data)
        args = (key, location, data, expiration, deferred)
        d.addCallbacks(self._post_succeed, self._post_failed,
                       callbackArgs=args, errbackArgs=args)
        return d

    def _post_succeed(self, response, key, _loc, _data, _exp, d):
        d.callback(True)

    def _post_failed(self, failure, key, loc, data, exp, d):
        self.debug("failed to post message to %s, putting it in quarantine",
                   self._key2url(key))
        self._add_pending(key, loc, data, exp, d)
        self._quarantined.add(key)
        self._schedule_retry(key)

    def _cleanup_expired(self, key, now=None):
        now = now if now is not None else time.time()
        not_expired = []

        for d, loc, data, exp in self._pendings[key]:
            if exp is None or exp > now:
                not_expired.append((d, loc, data, exp))
            else:
                d.callback(False)

        if not_expired:
            self._pendings[key] = not_expired
        else:
            del self._pendings[key]

    def _post_pendings(self, key, now=None):
        now = now if now is not None else time.time()
        for d, loc, data, exp in self._pendings[key]:
            self._post(key, loc, data, exp, now, d)
        del self._pendings[key]

    def _reset_retry(self, key):
        if key in self._delays:
            del self._delays[key]
        if key in self._retries:
            callid = self._retries[key]
            if callid.active():
                callid.cancel()
            del self._retries[key]

    def _schedule_retry(self, key):
        if key in self._retries:
            return

        delay = self._next_retry_delay(key)
        callid = time.call_later(delay, self._do_retry, key)
        self._retries[key] = callid
        self._delays[key] = delay

    def _do_retry(self, key):
        del self._retries[key]
        self._cleanup_expired(key)
        if key in self._pendings:
            # Do not connect if all pending messages are expired
            self._connect(key)
        else:
            self._quarantined.remove(key)
            self._reset_retry(key)

    def _cancel_retries(self):
        for callid in self._retries.itervalues():
            if callid and callid.active():
                callid.cancel()
        self._retries.clear()

    def _next_retry_delay(self, key):
        delay = self._delays.get(key, self.initial_delay)

        delay = min(delay * self.factor, self._max_delay)
        if self.jitter:
            delay = random.normalvariate(delay, delay * self.jitter)

        return delay

    def _fatal_error(self, key, message):
        pendings = self._pendings.get(key, [])
        del self._pendings[key]
        self.error("Fatal tunneling error, dropping %d message for %s: %s ",
                   len(pendings), self._key2url(key), message)
        if key in self._quarantined:
            self._quarantined.remove(key)
        for d, _path, _data, _exp in pendings:
            d.callback(False)

    def _key2url(self, key):
        scheme, host, port = key
        return http.compose(host=host, port=port, scheme=scheme)


class Peer(httpclient.Connection):
    """A connection to a tunnel server.
    First head() should be called to setup serializer and version,
    If not, the other side may not understand the current version."""

    def __init__(self, tunnel, key, security_policy=None):
        # Overriding default factory timeouts plus a small margin
        if tunnel.response_timeout is not None:
            self.response_timeout = tunnel.response_timeout

        if tunnel.idle_timeout is not None:
            self.idle_timeout = tunnel.idle_timeout

        _scheme, host, port = key
        httpclient.Connection.__init__(self, host, port=port,
                                       security_policy=security_policy,
                                       logger=tunnel)
        self._tunnel = tunnel
        self._key = key
        self._peer_version = None
        self._target_version = None
        self._headers = {}

        self._headers["host"] = "%s:%d" % (host, port)
        self._headers["content-type"] = "application/json"
        ver = tunnel._version
        self._headers["user-agent"] = http.compose_user_agent(FEAT_IDENT, ver)

    ### public ###

    def head(self, location):
        d = self.request(http.Methods.HEAD, location, headers=self._headers)
        d.addCallback(self._update_peer_version)
        return d

    def post(self, location, data):
        body = self._serialize(data)
        return self.request(http.Methods.POST, location, self._headers, body)

    ### overridden ###

    def onClientConnectionFailed(self, reason):
        httpclient.Connection.onClientConnectionFailed(self, reason)
        self._tunnel._remove_peer(self._key)
        self._tunnel = None

    def onClientConnectionLost(self, protocol, reason):
        httpclient.Connection.onClientConnectionLost(self, protocol, reason)
        self._tunnel._remove_peer(self._key)
        self._tunnel = None

    ### private ###

    def _update_peer_version(self, response):
        vser = None

        server_header = response.headers.get("server", None)
        if server_header is not None:
            server_name, server_ver = http.parse_user_agent(server_header)
            if (server_name != FEAT_IDENT
                or len(server_ver) != 1
                or not isinstance(server_ver[0], int)):
                raise TunnelError("Unsupported server %r" % server_header)
            vser = server_ver[0]

        vin = self._tunnel._version
        vout = vser if vser is not None and vser < vin else vin
        self._peer_version = vser
        self._target_version = vout

        self._headers["user-agent"] = http.compose_user_agent(FEAT_IDENT, vout)

        return response

    def _serialize(self, data):
        vin = self._tunnel._version
        vtar = self._target_version
        vout = vtar if vtar is not None else vin
        serializer = json.Serializer(indent=2, force_unicode=True,
                                     source_ver=vin, target_ver=vout)
        self._headers["user-agent"] = http.compose_user_agent(FEAT_IDENT, vout)
        return serializer.convert(data)


class Request(httpserver.Request):

    def __init__(self, channel, info, active):
        httpserver.Request.__init__(self, channel, info, active)
        self._registry = channel.owner._registry
        self._buffer = []

    def dataReceived(self, data):
        self._buffer.append(data)

    def onAllContentReceived(self):
        vout = self.channel.owner._version

        ctype = self.get_received_header("content-type")
        if ctype != "application/json":
            self._error(http.Status.UNSUPPORTED_MEDIA_TYPE,
                        "Message content type not supported, "
                        "only application/json is.")
            return

        agent_header = self.get_received_header("user-agent")
        if agent_header is None:
            self._error(http.Status.BAD_REQUEST, "No user agent specified.")
            return

        agent_name, agent_ver = http.parse_user_agent(agent_header)
        if ((agent_name != FEAT_IDENT)
            or len(agent_ver) != 1
            or not isinstance(agent_ver[0], int)):
            self._error(http.Status.BAD_REQUEST, "User agent not supported.")
            return

        vcli = agent_ver[0]

        if self.method is http.Methods.HEAD:
            vin = vcli if vcli is not None and vcli < vout else vout
            server_header = http.compose_user_agent(FEAT_IDENT, vin)
            self.set_header("server", server_header)
            self.set_length(0)
            self.finish()
            return

        if self.method is http.Methods.POST:
            if vcli is not None and vcli > vout:
                # not safe, better fail
                self._error(http.Status.UNSUPPORTED_MEDIA_TYPE,
                            "Message version not supported.")
                return

            host_header = self.get_received_header("host")
            if host_header is None:
                self._error(http.Status.BAD_REQUEST,
                            "Message without host header.")
                return

            scheme = self.channel.owner._scheme
            host, port = http.parse_host(host_header, scheme)
            uri = http.compose(self.uri, host=host, port=port, scheme=scheme)

            vin = vcli if vcli is not None else vout
            unserializer = json.Unserializer(registry=self._registry,
                                             source_ver=vin, target_ver=vout)
            body = "".join(self._buffer)
            try:
                data = unserializer.convert(body)
            except Exception as e:
                msg = "Error while unserializing tunnel message"
                error.handle_exception(self, e, msg)
                self._error(http.Status.BAD_REQUEST,
                            "Invalid message, unserialization failed.")
                return

            self.channel.owner._dispatch(uri, data)

            self.set_response_code(http.Status.OK)
            server_header = http.compose_user_agent(FEAT_IDENT, vin)
            self.set_header("server", server_header)
            self.set_length(0)
            self.finish()
            return

        self.set_response_code(http.Status.NOT_ALLOWED)
        self.set_header("content-type", "plain/text")
        self.write("Method not allowed, only POST and HEAD.")
        self.finish()

    def _error(self, status, message=None):
        if not self.writing:
            self.clear_headers()
            self.set_response_code(status)
            ver = self.channel.owner._version
            self.set_header("server", "%s/%s" % (FEAT_IDENT, ver))
            if message:
                self.set_header("content-type", "plain/text")
                self.write(message)
        self.finish()


class RequestFactory(httpserver.RequestFactory):
    request_class = Request
