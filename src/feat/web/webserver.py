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

from cStringIO import StringIO
import os
import re
import sys
import time
import tempfile
import types

from zope.interface import Interface, Attribute, implements

from twisted.internet import reactor
from twisted.python.failure import Failure
from twisted.web import server, resource, http as webhttp

from feat.common import log, defer, error, decorator, signal
from feat.web import http, compat, document, auth, security


### Errors ###


class WebError(error.FeatError):

    default_error_name = "Web Server Error"


class AlreadyPreparedError(WebError):

    default_error_name = "Web Response Already Prepared"


### Interfaces ###


class IWebStatistics(Interface):
    '''
    Implemented by log writer for the webserver.
    '''

    def init():
        '''
        Called during webserver initialization.
        '''

    def request_finished(request, response):
        '''
        Called when processing of the request is finished.

        @param request: L{IWebRequest}
        @param response: L{IWebResponse}
        '''

    def cleanup():
        '''
        Called when the webserver is shuting down.
        You should close all the filedescriptors, release signals, etc.
        '''


class IWebResource(Interface):

    authenticator = Attribute("None or IAuthenticator")
    authorizer = Attribute("None or IAuthorizer")

    def set_inherited(self, authenticator=None, authorizer=None):
        """Sets the attributes inherited from the parent resource.
        Should be called by parent resources when adding a sub-resource."""

    def is_method_allowed(request, location, method):
        """Returns if the specified request method is allowed."""

    def get_allowed_methods(request, location):
        """Returns the list of allowed methods."""

    def locate_resource(request, location, remaining):
        """
        Must return:
         -  IWebResource :
                The leaf resource to use to render the resource
                The new location will be::
                  new_loc = old_loc + old_rem
         -  (IWebResource, remaining) :
                An intermediary resource to use to continue
                resource location. The new location will be::
                  new_loc = old_loc + old_rem[:len(old_rem) - len(rem)]
                if remaining size is smaller than old_rem.
                Otherwise the oldLocation does not change.
         -  (IWebResource, location, remaining) :
                An intermediary resource to use to continue
                resource location. The new location will be the returned one.

        Can return a Deferred.
        Modifying the location can be used to dynamically and transparently
        rewrite the resource location. The final location will be used for
        authentication and authorization.
        """

    def render_resource(request, response, location):
        """
        Processes the request, and return a status code
        or a Deferred that fire a status code.
        The response content should be written using the response reference.
        May raise or fire a WebError with an error code.
        """

    def render_error(request, response, error):
        """
        Render an error.
        Can return a Deferred
        """


class IWebRequest(Interface):

    peer = Attribute("")
    peer_info = Attribute("security.IPeerInfo")
    is_secured = Attribute("")
    domain = Attribute("")
    scheme = Attribute("")
    path = Attribute("")
    location = Attribute("")
    arguments = Attribute("")
    method = Attribute("")
    credentials = Attribute("")
    mime_type = Attribute("")
    encoding = Attribute("")
    language = Attribute("")
    accepted_mime_types = Attribute("")
    accepted_encodings = Attribute("")
    accepted_languages = Attribute("")
    length = Attribute("")
    context = Attribute("")
    cancelled = Attribute("C{bool} set if the underlying connection was "
                          "closed before the response has been rendered ")
    received = Attribute("C{float} epoch time this request was parsed")

    def get_header(key):
        """Returns a request header."""

    def get_cookie(name):
        """Returns a request cookie."""

    def does_accept_mime_type(mime_type):
        """Returns if the request is accepting the specified mime-type."""

    def does_accept_encoding(encoding):
        """Returns if the request is accepting the specified encoding."""

    def does_accept_language(language):
        """Returns if the request is accepting the specified language."""

    def reset():
        """
        Returns to the start of the input data stream.
        """

    def read_object(*ifaces):
        """
        Return a deferred fired with read documents.
        """

    def get_object():
        """Return the object read before by calling read_object()
        or raise documents.ReadError if not read yet."""

    def wait_finished():
        """
        Returns a Deferred that will be fired with the response
        when finished or with a failure if something append.
        Can be used to detect when the connection has been lost
        before the request could be fulfilled.
        """


class IWebResponse(Interface):

    request = Attribute("")
    location = Attribute("")
    status = Attribute("")
    mime_type = Attribute("")
    encoding = Attribute("")
    language = Attribute("")
    caching_policy = Attribute("")
    expiration_policy = Attribute("")
    finished = Attribute("C{float} epoch time web the response was finished")
    bytes = Attribute("C{int} number of bytes transfered")

    # Flags
    can_update_headers = Attribute("")
    has_started_writing = Attribute("")
    is_prepared = Attribute("")

    def do_not_cache():
        """
        Instructs the response to not cache data,
        and flush currently cached data.
        If the response cache is not empty,
        the response preparation will be forced.
        """

    def set_status(code, message=None):
        """Sets the response status code,
        fail if the headers were already sent."""

    def set_length(length):
        """Sets the response length if known,
        fail if the headers were already sent."""

    def set_header(key, value):
        """Sets a response header,
        fail if the headers were already sent."""

    def get_header(key):
        """Returns a value of previously set header."""

    def set_encoding(encoding):
        """Sets the response encoding,
        fail if the headers were already sent."""

    def force_encoding(encoding):
        """Sets the response encoding,
        regardless of what client accepts."""

    def set_mime_type(mime_type):
        """Sets the response mime-type,
        fail if the headers were already sent."""

    def force_mime_type(mime_type):
        """
        Used in emergency cases to force the mime-type
        to be able to return an error.
        """

    def set_language(language):
        """Sets the response language,
        fail if the headers were already sent."""

    def set_caching_policy(policy):
        """Sets the response caching policy,
        fail if the headers were already sent."""

    def set_expiration_policy(policy):
        """Sets the response expiration policy,
        fail if the headers were already sent."""

    def add_cookie(name, payload, expires=None, max_age=None,
                   domain=None, path=None, secure=None):
        """
        Set an outgoing HTTP cookie.
        the payload should not contain ';' character.

        expire should be None or a datetime.datetime instance.
        max_age should be None or a or int (number of seconds)
        """

    def prepare():
        """
        Prepare the response. After this call, none of the setters
        set_header, set_encoding, set_mime_type, set_language,
        set_caching_policy, set_expiration_policy, add_cookie can be called.
        If not set, the default values will be used.
        """

    def write_object(obj, *args, **kwargs):
        """
        Writes an object using mime-type negotiation.
        The extra arguments and keyworkd arguments are passed
        through to the writer.
        @param obj: object to write.
        @type obj: object
        """


class INegotiable(Interface):
    """An object that can be negotiated for encoding and language."""

    allowed_encodings = Attribute("")
    allowed_languages = Attribute("")


### decorators ###


@decorator.parametrized_function
def read_object(function, iface, *default):

    def wrapper(self, request, *args, **kwargs):

        def got_object(obj):
            return function(self, obj, request, *args, **kwargs)

        def error(failure):
            if failure.check(document.DocumentFormatError):
                raise http.BadRequestError(failure.getErrorMessage(),
                                           cause=failure.value)
            failure.trap(http.BadRequestError)
            if default:
                return function(self, default[0], request, *args, **kwargs)
            return failure

        if len(default) > 1:
            raise TypeError("Only on default value allowed: %r"
                            % (args, ))

        d = request.read_object(iface)
        d.addCallbacks(got_object, error)
        return d

    return wrapper


### Classes ###


class ResourceMixin(object):

    __slots__ = ()

    implements(IWebResource)

    _action_lookup = {http.Methods.GET: "action_GET",
                      http.Methods.POST: "action_POST",
                      http.Methods.PUT: "action_PUT",
                      http.Methods.DELETE: "action_DELETE"}

    def __str__(self):
        return "<%s>" % type(self).__name__

    ### IWebResource ###

    @property
    def authenticator(self):
        return getattr(self, "_authenticator", None)

    @property
    def authorizer(self):
        return getattr(self, "_authorizer", None)

    def set_inherited(self, authenticator=None, authorizer=None):
        # Multiple authenticator or authorizer is not supported

        old_author = self.authorizer
        old_authen = self.authenticator
        new_author = None
        new_authen = None

        if authenticator is not None:
            new_authen = auth.IAuthenticator(authenticator)
        if authorizer is not None:
            new_author = auth.IAuthorizer(authorizer)

        if new_authen is not None:
            assert old_authen is None or new_authen is old_authen
            self._authenticator = new_authen

        if new_author is not None:
            assert old_author is None or new_author is old_author
            self._authorizer = new_author

    def is_method_allowed(self, request, location, methode):
        return hasattr(self, self._action_lookup.get(methode, None))

    def get_allowed_methods(self, request, location):
        return [m for m, a in self._action_lookup.items() if hasattr(self, a)]

    def locate_resource(self, request, location, remaining):
        return self, ()

    def render_resource(self, request, response, location):
        method = request.method
        if not self.is_method_allowed(request, location, method):
            allowed = self.get_allowed_methods(request, location)
            raise http.NotAllowedError(allowed_methods=allowed)

        handler = getattr(self, 'action_' + method.name, None)

        if not handler:
            allowed = self.get_allowed_methods(request, location)
            raise http.NotAllowedError(allowed_methods=allowed)

        return handler(request, response, location)

    def render_error(self, request, response, error):
        #FIXME: doing so destroy the original stack trace
        return error


class LeafResourceMixin(ResourceMixin):

    ### IWebResource ###

    def locate_resource(self, request, location, remaining):
        if remaining and (remaining != (u'', )):
            return None
        return self


class BaseResource(ResourceMixin):

    __slots__ = ("_authenticator", "_authorizer")

    def __init__(self, authenticator=None, authorizer=None):
        self._authenticator = authenticator
        self._authorizer = authorizer


class BasicResource(BaseResource):

    def __init__(self, authenticator=None, authorizer=None):
        BaseResource.__init__(self, authenticator, authorizer)
        self._children = {}

    def __setitem__(self, name, child):
        child.set_inherited(authenticator=self._authenticator,
                            authorizer=self._authorizer)
        self._children[name] = child

    def __getitem__(self, name):
        return self._children[name]

    def __delitem__(self, name):
        del self._children[name]

    def locate_resource(self, request, location, remaining):
        if not remaining or remaining == (u'', ):
            return self
        return self.locate_child(request, location, remaining)

    def locate_child(self, request, location, remaining):
        next = remaining[0]
        if next in self._children:
            return self._children[next], remaining[1:]


class ELFLog(object):
    '''
    Formats the extended log.

    @param path: where to store the file
    @param format: list of fields separated with spaces,
                   the supported values are:
                    - time
                    - date
                    - cs-method
                    - cs-uri
                    - bytes
                    - time-taken
                    - c-ip
                    - s-ip
                    - sc-status status code
                    - sc-comment comment returned with the status code
                    - cs-uri-stem
                    - cs-uri-query
                    - sc-comment
                    - sc(NAME) response header NAME value
                    - cs(NAME) request header NAME value
    @param dateformat: use it to override the date format used
    @param timeformat: use it to override the time format used
    '''

    implements(IWebStatistics)

    def __init__(self, path, format, dateformat="%d-%m-%Y",
                 timeformat="%H:%M:%S"):
        self._path = path
        self._format = format
        self._timeformat = timeformat
        self._dateformat = dateformat
        # field -> handler
        self._template_parts = list()

        # build the mapping of the handlers to call on each part,
        # validate the input format
        extracter = re.compile('^(sc|cs)\(([a-z\-]+)\)$', re.I)
        for field in format.split(" "):
            search = extracter.search(field)
            if search:
                handler_name = '_extract_%s' % (search.group(1), )
                handler = getattr(self, handler_name, None)
                if not callable(handler):
                    raise ValueError("Invalid field '%s'" % (field, ))
                handler = handler(search.group(2))
            else:
                handler_name = '_get_%s' % (field.replace('-', '_'), )
                handler = getattr(self, handler_name, None)
            if not callable(handler):
                raise ValueError("Invalid field '%s'" % (field, ))
            self._template_parts.append((field, handler))

        self._template = " ".join("%%(%s)s" % (x[0], )
                                  for x in self._template_parts)
        self._template += "\n"

    ### IWebStatistics ###

    def init(self):
        signal.signal(signal.SIGHUP, self._sighup_handler)
        self._reopen_output_file()

    def request_finished(self, request, response):
        data = dict((name, handler(request, response))
                    for name, handler in self._template_parts)
        self._output.write(self._template % data)
        self._output.flush()

    def cleanup(self):
        try:
            signal.unregister(signal.SIGHUP, self._sighup_handler)
        except ValueError:
            # this happens when cleanup() is called when init()
            # was not called before.
            pass
        if hasattr(self, '_output'):
            self._output.close()
            del self._output

    ### extracting data ###

    def _extract_cs(self, name):

        def _extract_cs(request, response):
            return '"%s"' % (request.get_header(name) or '', )

        return _extract_cs

    def _extract_sc(self, name):

        def _extract_sc(request, response):
            return '"%s"' % (response.get_header(name) or '', )

        return _extract_sc

    def _get_time(self, request, response):
        return time.strftime(self._timeformat,
                             time.localtime(request.received))

    def _get_date(self, request, response):
        return time.strftime(self._dateformat,
                             time.localtime(request.received))

    def _get_cs_method(self, request, response):
        return str(request.method.name)

    def _get_cs_uri(self, request, response):
        r = self._get_cs_uri_stem(request, response)
        query = self._get_cs_uri_query(request, response)
        if query:
            r += query
        return r

    def _get_cs_uri_stem(self, request, response):
        return request.path.split('?')[0]

    def _get_cs_uri_query(self, request, response):
        if request.arguments:
            return "?" + http.compose_qs(request.arguments)
        else:
            return ""

    def _get_bytes(self, request, response):
        return response.bytes

    def _get_time_taken(self, request, response):
        delta = response.finished - request.received
        idelta = int(delta)
        return "%s:%s:%1.2f" % (idelta / 3600, idelta /60, delta % 60)

    def _get_c_ip(self, request, response):
        return request.peer.host

    def _get_s_ip(self, request, response):
        return request._ref.host.host

    def _get_sc_status(self, request, response):
        return int(response.status)

    def _get_sc_comment(self, request, response):
        return str(http.Status[self._get_sc_status(request, response)].name)

    ### private ###

    def _sighup_handler(self, signum, frame):
        self._reopen_output_file()

    def _reopen_output_file(self):
        if os.path.exists(self._path):
            self._output = open(self._path, 'a')
        else:
            self._output = open(self._path, 'w')
            dt_format = " ".join([self._dateformat, self._timeformat])
            self._output.write("#Version: 1.0\n#Date: %s\n#Fields: %s\n" %
                               (time.strftime(dt_format), self._format))
            self._output.flush()


class HTTPChannel(webhttp.HTTPChannel):

    def connectionMade(self):
        self.factory.clientConnectionMade(self)
        webhttp.HTTPChannel.connectionMade(self)

    def connectionLost(self, reason):
        webhttp.HTTPChannel.connectionLost(self, reason)
        self.factory.clientConnectionLost(self)


class Site(server.Site, log.Logger):
    '''This site tracks all the connection made, and expose methods to:
    - close them.
    - wait for current requests to finish
    '''

    protocol = HTTPChannel

    def __init__(self, resource, log_keeper=None):
        server.Site.__init__(self, resource)
        log.Logger.__init__(self, log_keeper or log.get_default())
        self.connections = list()
        self._notifier = defer.Notifier()

    def clientConnectionMade(self, protocol):
        peer = protocol.transport.getPeer()
        self.debug("New HTTP connection from %s:%s", peer.host, peer.port)
        self.connections.append(protocol)

    def clientConnectionLost(self, protocol):
        self.debug("HTTP connection closed.")
        self.connections.remove(protocol)
        if not self.connections:
            self.debug('Site is idle.')
            self._notifier.callback('idle', None)

    def cleanup(self):
        '''
        Cleans up existing connections giving them time to finish the currect
        request.
        '''
        self.debug("Cleanup called on Site.")
        if not self.connections:
            return defer.succeed(None)
        self.debug("Waiting for all the connections to close.")
        result = self._notifier.wait('idle')
        for connection in self.connections:
            connection.persistent = False
            if not connection.requests:
                connection.transport.loseConnection()
            else:
                request = connection.requests[0]
                peer = connection.transport.getPeer()
                self.debug("Site is still processing a %s request from %s:%s"
                           " to path: %s. It will be given a time to finish",
                           request.method, peer.host, peer.port, request.path)
        return result

    def disconnectAll(self):
        '''
        Disconnect all the clients NOW, regardless if they process a request
        at the moment.
        '''
        if not self.connections:
            return defer.succeed(None)
        result = self._notifier.wait('idle')
        for connection in self.connections:
            connection.transport.loseConnection()
        return result


class Server(log.LogProxy, log.Logger):

    log_category = 'webserver'

    def __init__(self, port, root_resource, registry=None,
                 security_policy=None, server_identity=None,
                 default_authenticator=None, default_authorizer=None,
                 log_keeper=None, web_statistics=None,
                 interface=''):
        self.log_name = ":%s" % (port, )
        log.Logger.__init__(self, self)
        log_keeper = log_keeper or log.get_default() or log.FluLogKeeper()
        log.LogProxy.__init__(self, log_keeper)
        self._port = port
        self._resource = root_resource
        self._registry = registry or document.get_registry()
        self._policy = security.ensure_policy(security_policy)
        self._secured = False
        self._identity = server_identity
        self._authenticator = default_authenticator
        self._authorizer = default_authorizer
        self.statistics = web_statistics and IWebStatistics(web_statistics)
        self._interface = interface

        self._scheme = None
        self._mime_types = {}

        self._listener = None
        self._site = None

    def initiate(self):
        assert self._listener is None
        self.info("Initializing HTTP server...")
        self._site = site = Site(RootResourceWrapper(self), log_keeper=self)
        if self._policy.use_ssl:
            ssl_context_factory = self._policy.get_ssl_context_factory()
            self.info('SSL listening on port %r', self._port)
            listener = reactor.listenSSL(self._port, site, ssl_context_factory,
                                         interface=self._interface)
            self._secured = True
            self._scheme = http.Schemes.HTTPS
        else:
            self.info('TCP listening on port %r', self._port)
            listener = reactor.listenTCP(self._port, site,
                                         interface=self._interface)
            self._scheme = http.Schemes.HTTP
        self._listener = listener
        if self.statistics:
            self.statistics.init()

        return defer.succeed(self)

    def cleanup(self):
        if self.statistics:
            self.statistics.cleanup()
        defers = list()
        if self._listener:
            d = self._listener.stopListening()
            defers.append(d)
            self._listener = None
        if self._site:
            d = self._site.cleanup()
            defers.append(d)
            self._site = None
        if defers:
            d = defer.DeferredList(defers)
            d.addCallback(defer.override_result, self)
            return d
        else:
            return defer.succeed(self)

    @property
    def host(self):
        return self._listener and self._listener.getHost().host

    @property
    def port(self):
        return self._listener and self._listener.getHost().port

    @property
    def authenticator(self):
        return self._authenticator

    @property
    def authorizer(self):
        return self._authorizer

    @property
    def is_secured(self):
        return self._secured

    @property
    def scheme(self):
        return self._scheme

    @property
    def identity(self):
        return self._identity

    @property
    def registry(self):
        return self._registry

    def enable_mime_type(self, mime_type, priority=0.5):
        type, sub = http.mime2tuple(mime_type)
        self._mime_types.setdefault(type, {})[sub] = min(1.0, float(priority))

    def negotiate_mime_types(self, obj, accepts={}):
        acc_types = http.build_mime_tree(accepts, True)
        priorities = {}
        for doc_type, doc_subtypes in self._mime_types.items():
            acc_subtypes = acc_types.get(doc_type, acc_types["*"])
            for doc_subtype, doc_pri in doc_subtypes.items():
                acc_pri = acc_subtypes.get(doc_subtype, acc_subtypes["*"])
                priority = doc_pri * acc_pri
                mime_type = http.tuple2mime((doc_type, doc_subtype))
                if self._registry.lookup_writer(mime_type, obj):
                    priorities[mime_type] = priority
        order = priorities.keys()
        order.sort(key=priorities.get)
        return order[::-1]

    def negotiate_forced_aspect(self, options, accepts):
        """Order specified options in function of the specified
        accept priorities."""
        if not options:
            return None

        priorities = {}

        for i, o in enumerate(options):
            p = accepts.get(o, None)
            if p is None:
                p = accepts.get("*", None)
            if p is not None:
                # Prevent that a priority of 0 mess with the order of options
                priorities[o] = max(p, 0.000001) * (1 - i * 0.1 / len(options))

        if not priorities:
            return None

        order = priorities.keys()
        order.sort(key=priorities.get)
        return order[::-1]

    ### private ###

    def _process_request(self, priv_request):
        peer_info = self._policy.get_peer_info(priv_request.channel.transport)

        request = None
        response = None

        try:

            # First create request and response parsing HTTP headers and so
            request = Request(self, priv_request, peer_info)
            response = Response(self, request)

        except Exception, e:

            # Early error, just log and respond something that make sense
            msg = "Exception during HTTP request creation"
            error.handle_exception(self, e, msg)
            status_code = http.Status.INTERNAL_SERVER_ERROR
            if isinstance(e, http.HTTPError):
                status_code = e.status_code
            priv_request.setResponseCode(int(status_code))
            priv_request.setHeader("content-type", "text/plain")
            return "Error: %s" % e

        try:

            # Initialize and set default values
            request._initialize()
            response._initialize()
            response.set_status(http.Status.OK)

            location = request.location

            if len(location) < 1:
                raise http.BadRequestError()
            elif location[0] != '':
                raise http.BadRequestError()

            # render the resource
            d = self._process_resource(request, response,
                                       self._resource, request.credentials,
                                       (u'', ), location[1:])

            if isinstance(d, defer.Deferred):
                # Asynchronous rendering
                d.addErrback(self._emergency_termination, request, response)
                d.addCallback(defer.drop_param, response._finish)
                # # _emergency_termination bridges through the CancelledError
                # # so that we don't try to finalize the response
                # d.addErrback(Failure.trap, defer.CancelledError)
                finished = request.wait_finished()
                finished.addErrback(defer.drop_param, d.cancel)
            else:
                response._finish()

            return server.NOT_DONE_YET

        except:

            self._emergency_termination(Failure(), request, response)
            response._finish()
            return server.NOT_DONE_YET


    ### private ###

    def _terminate(self, request, response, code=None):
        if response.can_update_headers:
            if code is not None:
                response.set_status(code)
        return None

    def _write_data(self, data, response):
        if data is None:
            return None

        if isinstance(data, (str, unicode)):
            response.write(data)
            return None

        return response.write_object(data)

    def _process_resource(self, request, response, resource,
                          credentials, location, remaining):
        try:
            d = self._authenticate_resource(request, response, resource,
                                            credentials, location,
                                            self._locate_resource, remaining)
            if isinstance(d, defer.Deferred):
                d.addErrback(self._process_failure,
                             request, response, resource)
                return d
        except:
            return self._process_failure(Failure(), request,
                                         response, resource)

    def _authenticate_resource(self, request, response, resource,
                               credentials, location, continuation, *args):
        authenticator = resource.authenticator or self._authenticator
        if authenticator:
            self.log("Authenticating request %s for path '%s' with %s",
                     request, http.tuple2path(location), resource)

            try:
                d = authenticator.authenticate(request, credentials, location)
                if isinstance(d, defer.Deferred):
                    args = (request, response, resource, credentials,
                            location, continuation, args)
                    d.addCallbacks(self._got_authentication_result,
                                   self._authentication_failed,
                                   callbackArgs=args, errbackArgs=args)
                    return d
            except:
                self._authentication_failed(Failure(), request, response,
                                            resource, credentials,
                                            location, continuation, args)
            else:
                return self._got_authentication_result(d, request, response,
                                                       resource, credentials,
                                                       location, continuation,
                                                       args)

        return continuation(request, response, resource,
                            credentials, location, *args)

    def _authentication_failed(self, failure, request, response, resource,
                               oldcred, location, _continuation, _args):
        if failure.check(http.NotAuthorizedError):
            return failure

        error.handle_failure(self, failure, "Failure during authentication")
        raise http.InternalServerError("Failure during authentication",
                                       cause=failure)

    def _got_authentication_result(self, newcred, request, response, resource,
                                   oldcred, location, continuation, args):
        if newcred is None:
            self.log("Resource %s do not need request %s to be authenticated",
                     resource, request)
            credentials = oldcred

        elif auth.IHTTPChallenge.providedBy(newcred):
            if oldcred is not None:
                self.log("Resource %s refused credentials provided "
                         "by request %s", resource, request)
            self.log("Resource %s need request %s to be authenticated",
                     resource, request)
            raise http.NotAuthorizedError(challenge=newcred)

        elif auth.IHTTPCredentials.providedBy(newcred):
            self.log("Resource %s authenticated for request %s",
                     resource, request)
            credentials = newcred

        else:
            raise http.InternalServerError("Invalid credentials type %s"
                                           % type(newcred).__name__)

        return continuation(request, response, resource,
                            credentials, location, *args)

    def _locate_resource(self, request, response, resource,
                         credentials, location, remaining):
        self.log("Locating resource for sub-path '%s'",
                 http.tuple2path(remaining))
        d = resource.locate_resource(request, location, tuple(remaining))
        if isinstance(d, defer.Deferred):
            return d.addCallback(self._resource_located, request, response,
                                 resource, credentials, location, remaining)

        return self._resource_located(d, request, response, resource,
                                      credentials, location, remaining)

    def _resource_located(self, result, request, response,
                          old_res, credentials, old_loc, old_rem):
        if ((result is None)
            or (isinstance(result, tuple) and (result[0] is None))):
            self.log("No resource found for sub-path '%s'",
                     http.tuple2path(old_rem))
            raise http.NotFoundError()

        if isinstance(result, tuple):

            if (len(result) < 1) or (len(result) > 3):
                raise http.InternalServerError("Invalid Resource Result")

            resource = result[0]
            if isinstance(resource, defer.Deferred):
                resource.addCallback(lambda r: (r, ) + result[1:])
                resource.addCallback(self._resource_located, request, response,
                                    old_res, credentials, old_loc, old_rem)
                return resource

            resource = IWebResource(resource)

            if len(result) == 1:
                new_rem = ()
                new_loc = old_loc + old_rem
            elif len(result) < 3:
                new_rem = ((len(result) > 1) and result[1]) or ()
                delta = len(old_rem) - len(new_rem)
                if delta > 0:
                    new_loc = old_loc + old_rem[:delta]
                else:
                    new_loc = old_loc
            else:
                new_loc = result[1]
                new_rem = result[2]

        else:

            resource = IWebResource(result)
            new_rem = ()
            new_loc = old_loc + old_rem

        if len(new_rem) > 0:
            # Still not a leaf, continue
            self.log("Intermediary resource %s found for sub-path '%s' "
                     "with remaining path '%s'", resource,
                     http.tuple2path(new_loc), http.tuple2path(new_rem))
            return self._process_resource(request, response, resource,
                                          credentials, new_loc, new_rem)
        else:
            # We found the leaf
            self.log("resource %s found for sub-path '%s'",
                     resource, http.tuple2path(new_loc))
            return self._start_rendering(request, response, resource,
                                         credentials, new_loc)

    def _start_rendering(self, request, response, resource,
                         credentials, location):
        try:
            d = self._authenticate_resource(request, response, resource,
                                            credentials, location,
                                            self._authorize_rendering)
            if isinstance(d, defer.Deferred):
                d.addErrback(self._process_failure,
                             request, response, resource)
                return d
        except:
            return self._process_failure(Failure(), request,
                                         response, resource)

    def _authorize_rendering(self, request, response, resource,
                             credentials, location):
        response._set_location(location)
        authorizer = resource.authorizer or self._authorizer

        if authorizer:
            self.log("Authorizing request %s for path '%s'",
                     request, http.tuple2path(location))
            d = authorizer.authorize(request, credentials, location)

            if isinstance(d, defer.Deferred):
                args = (request, response, resource, location)
                d.addCallbacks(self._got_authorization,
                                        self._authorization_failed,
                                        callbackArgs=args, errbackArgs=args)
                return d

            return self._got_authorization(d, request, response,
                                           resource, location)

        return self._render_resource(request, response, resource, location)

    def _authorization_failed(self, failure, request, response,
                              resource, location):
        raise http.InternalServerError("Failure during authorization",
                                       cause=failure)

    def _got_authorization(self, authorized, request, response,
                           resource, location):
        if not authorized:
            self.log("Request %s not authorized for resource %s "
                     "with path '%s'", request, resource,
                     http.tuple2path(location))
            raise http.ForbiddenError("Resource Access Forbidden")

        self.log("Request %s authorized for resource %s with path '%s'",
                 request, resource, http.tuple2path(location))
        return self._render_resource(request, response, resource, location)

    def _render_resource(self, request, response, resource, location):
        self.log("Rendering path '%s' for request %s",
                 http.tuple2path(location), request)
        d = resource.render_resource(request, response, location)
        if isinstance(d, defer.Deferred):
            return d.addCallback(self._resource_rendered, request, response)
        return self._resource_rendered(d, request, response)

    def _resource_rendered(self, data, request, response):
        if data is not response:
            d = self._write_data(data, response)
            if isinstance(d, defer.Deferred):
                d.addCallback(defer.drop_param,
                              self._terminate, request, response)
                return d

        return self._terminate(request, response)

    def _process_failure(self, failure, request, response, resource):
        error = self._prepare_error(failure, request, response)
        if error is None:
            # Error has been resolved
            return self._terminate(request, response)

        return self._render_error(request, response, resource, error)

    def _prepare_error(self, failure, request, response):
        exception = failure.value
        if isinstance(exception, http.NotAuthorizedError):

            if response.can_update_headers:
                challenge = exception.challenge
                if challenge:
                    header = challenge.header_value
                    response.set_header('WWW-Authenticate', header)
                    response.set_status(http.Status.UNAUTHORIZED)

        elif isinstance(exception, http.NotAcceptableError):

            if response.can_update_headers:
                # Add NON-STANDARD headers to the response
                if exception.allowed_mime_types:
                    allowed = ", ".join(exception.allowed_mime_types)
                    response.set_header('Allow-Type', allowed)
                if exception.allowed_encodings:
                    allowed = ", ".join(exception.allowed_encodings)
                    response.set_header('Allow-Charset', allowed)
                if exception.allowed_languages:
                    allowed = ", ".join(exception.allowed_languages)
                    response.set_header('Allow-Language', allowed)
                response.set_status(http.Status.NOT_ACCEPTABLE)

        elif isinstance(exception, http.NotAllowedError):

            if response.can_update_headers:
                value = ", ".join([m.name for m in exception.allowed_methods])
                response.set_header('Allow', value)
                response.set_status(http.Status.NOT_ALLOWED)

        elif isinstance(exception, http.MovedPermanently):

            if response.can_update_headers:
                response.set_header('Location', exception.location)
                response.set_status(http.Status.MOVED_PERMANENTLY)
                response.set_header("Cache-Control", "no-store")
                response.set_header("connection", "close")

                return None

        elif isinstance(exception, http.HTTPError):

            if response.can_update_headers:
                response.set_status(exception.status_code)

            if not exception.status_code.is_error():
                # Not a real error, so we terminate
                return None

        elif isinstance(exception, UnicodeEncodeError):

            # We failed to encode data in the response selected charset
            # As for HTTP/1.1 we should set the accepted characteristics,
            # but it would be hard at this point given we don't know what
            # triggered this exception.
            msg = "Failed to encode response to accepted charset"
            self.debug(msg)
            if response.can_update_headers:
                response.set_status(http.Status.NOT_ACCEPTABLE)

        elif isinstance(exception, defer.CancelledError):
            self.debug("Request processing was cancelled. This is a normal "
                       "behaviour when the underlying connection is closed "
                       "by the client.")
            request.cancelled = True
            return None
        else:

            msg = "Exception during HTTP resource rendering"
            error.handle_failure(self, failure, msg)
            if response.can_update_headers:
                response.set_status(http.Status.INTERNAL_SERVER_ERROR)

        return exception

    def _render_error(self, request, response, resource, error):
        if response.has_started_writing:
            # Nothing we can do now
            return self._terminate(request, response)

        response._try_reset()

        d = resource.render_error(request, response, error)

        if isinstance(d, defer.Deferred):
            d.addCallback(self._error_rendered, request, response, error)
            return d

        return self._error_rendered(d, request, response, error)

    def _error_rendered(self, data, request, response, error):
        if data is response:
            return self._terminate(request, response)

        if data is error:
            # Trying to keep the backtrace
            exc_info = sys.exc_info()
            if exc_info and exc_info[0]:
                raise exc_info[0], exc_info[1], exc_info[2]
            else:
                raise error

        if data and not response.has_started_writing:
            d = self._write_data(data, response)
            if isinstance(d, defer.Deferred):
                d.addCallback(defer.drop_param,
                              self._terminate, request, response)
                return d

        return self._terminate(request, response)

    def _emergency_termination(self, failure, request, response):

        if failure.check(defer.CancelledError):
            # This happens when the request is broken before the handler
            # renders it. This case is handled in _prepare_error().
            return failure

        try:
            if not failure.check(http.HTTPError):
                msg = "Unrecovered Failure During Web Request"
                error.handle_failure(self, failure, msg)

            if response.can_update_headers:
                response.set_header("content-type", "text/plain")
                response.force_encoding('ascii')
                msg = failure.getErrorMessage()
                if msg:
                    response.write("Error: %s\n" % (msg, ))

            if failure.check(http.HTTPError):
                return self._terminate(request, response,
                                       failure.value.status_code)
            else:
                return self._terminate(request, response)

        except Exception, e:

            msg = "Exception during emergency termination"
            error.handle_exception(self, e, msg)

            # We don't call _terminate() here, we already too deep in the mess
            return None


### private ###


class Request(log.Logger, log.LogProxy):

    implements(IWebRequest, document.IReadableDocument)

    def __init__(self, server, priv_request, peer_info=None):
        log.Logger.__init__(self, server)
        log.LogProxy.__init__(self, server)
        self._server = server
        self._ref = priv_request
        self._secured = server.is_secured
        self._peer_info = peer_info

        self.log_name = ("%s on %s://%s:%s%s" %
                         (priv_request.method,
                          self._server.scheme.name,
                          priv_request.host.host,
                          priv_request.host.port,
                          priv_request.uri))
        self.received = time.time()
        self.debug("Parsing request from %s:%s", priv_request.client.host,
                   priv_request.client.port)

        content_type = self.get_header("content-type")
        mime_type, encoding = http.parse_content_type(content_type)
        language = self.get_header("content-language") or http.DEFAULT_LANGUAGE
        location = http.path2tuple(self._ref.path)
        accept = self.get_header("accept")
        accepted_mime_types = http.parse_accepted_types(accept)
        accept_tree = http.build_mime_tree(accepted_mime_types)
        accept_charset = self.get_header("accept-charset")
        accepted_encodings = http.parse_accepted_charsets(accept_charset)
        accept_languages = self.get_header("accept-languages")
        accepted_languages = http.parse_accepted_languages(accept_languages)

        try:
            method = http.Methods[self._ref.method]
        except KeyError:
            raise http.NotAllowedError("Method %s not supported"
                                       % (self._ref.method, )), \
                  None, sys.exc_info()[2]

        try:
            protocol = _protocol_lookup[self._ref.clientproto]
        except KeyError:
            raise http.BadRequestError("Protocol %s not supported"
                                       % (self._ref.clientproto, )), \
                  None, sys.exc_info()[2]

        self._mime_type = mime_type
        self._encoding = encoding
        self._language = language
        self._location = location
        self._accepted_mime_types = accepted_mime_types
        self._accept_tree = accept_tree
        self._accepted_encodings = accepted_encodings
        self._accepted_languages = accepted_languages
        self._method = method
        self._protocol = protocol
        self._credentials = None

        self._context = {} # Black box

        self._cancelled = False
        self._reading = False
        self._objects = []

        # Look for URI arguments only, the POST is content, not arguments
        uri_parts = self._ref.uri.split('?', 1)
        if len(uri_parts) > 1:
            arguments = http.parse_qs(uri_parts[1], True)
        else:
            arguments = {}

        # Look for domain information
        domain = self.get_header("host")
        if not domain:
            domain = "%s:%s" % (self._ref.host.host, self._ref.host.port)
        domain = self._decode(domain)
        content_length = self.get_header("content-length")
        length = content_length and int(content_length)

        # To prevent content being consumed
        # when it's application/x-www-form-urlencoded
        self._ref.content.seek(0, 0)

        self._arguments = arguments
        self._domain = domain
        self._length = length

    def __str__(self):
        return "<%s on %s>" % (self.method.name, self.path)

    ### IWebRequest ###

    @property
    def peer(self):
        return self._ref.client

    @property
    def peer_info(self):
        return self._peer_info

    @property
    def is_secured(self):
        return self._server.is_secured

    @property
    def scheme(self):
        return self._server.scheme

    @property
    def domain(self):
        return self._domain

    @property
    def protocol(self):
        return self._protocol

    @property
    def path(self):
        return self._ref.path

    @property
    def location(self):
        return self._location

    @property
    def arguments(self):
        return self._arguments

    @property
    def method(self):
        return self._method

    @property
    def credentials(self):
        return self._credentials

    @property
    def mime_type(self):
        return self._mime_type

    @property
    def encoding(self):
        return self._encoding

    @property
    def language(self):
        return self._language

    @property
    def accepted_mime_types(self):
        return self._accepted_mime_types

    @property
    def accepted_encodings(self):
        return self._accepted_encodings

    @property
    def accepted_languages(self):
        return self._accepted_languages

    @property
    def length(self):
        return self._length

    @property
    def context(self):
        return self._context

    @property
    def headers(self):
        return dict(
            (k, v[-1])
            for k, v in self._ref.requestHeaders.getAllRawHeaders())

    def _get_cancelled(self):
        return self._cancelled

    def _set_cancelled(self, value):
        self._cancelled = True

    cancelled = property(_get_cancelled, _set_cancelled)

    def get_header(self, key):
        header = self._ref.getHeader(key)
        if header and isinstance(header, str):
            return header.decode(http.HEADER_ENCODING)
        return header

    def get_cookie(self, name):
        return self._ref.getCookie(name)

    def does_accept_mime_type(self, mime_type):
        return http.does_accept_mime_type(mime_type, self._accept_tree)

    def does_accept_encoding(self, encoding):
        if encoding in self._accepted_encodings:
            return True
        if "*" in self._accepted_encodings:
            return True
        return False

    def does_accept_language(self, language):
        if language in self._accepted_languages:
            return True
        if "*" in self._accepted_languages:
            return True
        return False

    def reset(self):
        self._ref.content.seek(0)

    def wait_finished(self):
        d = self._ref.notifyFinish()
        d.addCallback(defer.override_result, self)
        return d

    @defer.ensure_async
    def read_object(self, *ifaces):
        try:
            if self._reading or self._objects:
                raise document.ReadError("Already reading an object")
            if not ifaces:
                raise document.ReadError("No object interface specified")
            self._reading = True
            return self._read_object(ifaces)
        except:
            self._reading = False
            raise

    def get_object(self):
        if not self._objects:
            raise document.ReadError("No object read yet")
        return self._objects[0]

    ### document.IReadableDocument ###

    def read(self, size=-1, decode=True):
        data = self._ref.content.read(size)
        res = self._decode(data) if decode else data
        limit = 1000
        limited = res if len(res) < limit else res[0:limit] + "..."
        self.debug("Read request body: %r", limited)
        return res

    def readline(self, size=-1, decode=True):
        data = self._ref.content.readline(size)
        return self._decode(data) if decode else data

    def readlines(self, sizehint=-1, decode=True):
        lines = self._ref.content.readlines(sizehint)
        return [self._decode(l) for l in lines] if decode else lines

    def __iter__(self):
        return (l for l in self.readline())

    ### protected ###

    def _initialize(self):
        header = self.get_header("authorization")
        if header:
            # Only support for basic authentication
            try:
                cred = auth.BasicHTTPCredentials.from_header_value(header)
            except Exception as e:
                self.debug("Invalid authorization header: %r", header)
                raise http.BadRequestError(cause=e)
            self._credentials = cred

    ### private ###

    def _decode(self, value):
        if (not value) or isinstance(value, unicode):
            return value
        return value.decode(self._encoding or http.DEFAULT_ENCODING)

    def _read_object(self, ifaces):
        d = self._server.registry.read(self, ifaces[0])
        d.addCallbacks(self._object_read_succeed,
                       self._object_read_failed,
                       errbackArgs=(ifaces, ))
        return d

    def _object_read_succeed(self, obj):
        self._objects.append(obj)
        self._reading = False
        return obj

    def _object_read_failed(self, failure, ifaces):
        if len(ifaces) <= 1:
            if failure.check(document.NoReaderFoundError):
                raise http.BadRequestError(cause=failure.value)
            self._reading = False
            return failure

        return self._read_object(ifaces[1:])


class Response(log.Logger):

    implements(IWebResponse, document.IWritableDocument)

    strict_negotiation = True

    # map encodings unknown to Python but used by browsers to what Python
    # knows how to handle
    ENCODING_TRANSLATION = {'x-gbk': 'gbk'}

    def __init__(self, server, request):
        log.Logger.__init__(self, request)
        self._server = server
        self._request = request
        self._encoding = None
        self._mime_type = None
        self._language = None
        self._cachingPolicy = None
        self._expirationPolicy = None
        self._prepared = False
        self._cache = StringIO()
        self._location = None

        self._writing = False
        self._objects = []
        self._finished = None
        self._bytes = 0
        self._cancelled = False

    ### IWebResponse ###

    @property
    def location(self):
        """Could be different from request location due to rewrite."""
        return self._location

    @property
    def request(self):
        return self._request

    @property
    def status(self):
        return http.Status(self._request._ref.code)

    @property
    def encoding(self):
        return self._encoding

    @property
    def mime_type(self):
        return self._mime_type

    @property
    def language(self):
        return self._language

    @property
    def caching_policy(self):
        return self._caching_policy

    @property
    def expiration_policy(self):
        return self._expiration_policy

    @property
    def can_update_headers(self):
        return self._cache is not None

    @property
    def has_started_writing(self):
        return self._cache is None

    @property
    def is_prepared(self):
        return self._prepared

    @property
    def finished(self):
        return self._finished

    @property
    def bytes(self):
        return self._bytes

    @property
    def headers(self):
        return dict(
            (k, v[-1])
            for k, v in self._request._ref.responseHeaders.getAllRawHeaders())

    @property
    def body(self):
        if self._cache:
            return self._cache.getvalue()
        raise ValueError("This Response is configured to write the response "
                         "directly to the socket file descriptor")

    def do_not_cache(self):
        data = self._cache and self._cache.getvalue()
        self._cache = None
        if data:
            self.write(data)

    def set_status(self, code, message=None):
        self._check_header_not_sent()
        self._request._ref.setResponseCode(int(code))

    def set_length(self, length):
        self.set_header("content-length", length)

    def set_header(self, key, value):
        self._check_header_not_sent()
        self._set_header(key, value)

    def get_header(self, key):
        headers = self._request._ref.responseHeaders.getRawHeaders(key)
        if headers and isinstance(headers, list):
            return headers[-1].decode(http.HEADER_ENCODING)
        return headers[-1]

    def set_encoding(self, encoding):
        self._check_header_not_sent()
        if self.strict_negotiation:
            if not self._request.does_accept_encoding(encoding):
                raise http.NotAcceptableError()
        self._encoding = encoding

    def force_encoding(self, encoding):
        self._check_header_not_sent()
        self._encoding = encoding

    def set_mime_type(self, mime_type):
        self._check_header_not_sent()
        if self.strict_negotiation:
            if not self._request.does_accept_mime_type(mime_type):
                self.debug("Refusing to set not accepted mime_type: %s. "
                           "Accept header: %s. Accept tree: %r", mime_type,
                           self._request.get_header('accept'),
                           self._request._accept_tree)
                raise http.NotAcceptableError()
        self._mime_type = mime_type

    def force_mime_type(self, mime_type):
        self._check_header_not_sent()
        self._mime_type = mime_type

    def set_language(self, language):
        self._check_header_not_sent()
        if self.strict_negotiation:
            if not self._request.does_accept_language(language):
                raise http.NotAcceptableError()
        self._language = language.lower()

    def set_caching_policy(self, policy):
        self._check_header_not_sent()
        self._cachingPolicy = policy

    def set_expiration_policy(self, policy):
        self._check_header_not_sent()
        self._expirationPolicy = policy

    def add_cookie(self, name, payload, expires=None, max_age=None,
                   domain=None, path=None, secure=None):
        self._check_header_not_sent()
        if expires:
            utctimestamp = time.mktime(expires.utctimetuple())
            expires = http.compose_datetime(utctimestamp)
        self._request._ref.addCookie(name, payload,
                                     expires=expires,
                                     domain=domain,
                                     path=path,
                                     max_age=max_age,
                                     comment=None,
                                     secure=secure)

    def prepare(self):
        if self._prepared:
            return
        self._prepared = True
        self._select_suitable_encoding()
        self._select_suitable_language()
        self._select_suitable_mime_type()
        self._update_headers()

    @defer.ensure_async
    def write_object(self, obj, *args, **kwargs):
        if not self._writing and self._objects:
            raise document.WriteError("Object already written")

        self._writing = True
        try:
            server = self._server
            request = self._request
            mime_type = self._mime_type

            if not mime_type:
                accept = request.accepted_mime_types
                mime_types = server.negotiate_mime_types(obj, accept)
                if not mime_types:
                    msg = "Requested mime-type not allowed"
                    raise http.NotAcceptableError(msg)
                mime_type = mime_types[0]
                self.set_mime_type(mime_type)

            if INegotiable.providedBy(obj):
                negotiable = INegotiable(obj)

                allowed_encodings = None
                encoding = self._encoding

                if not encoding:
                    accepted = request.accepted_encodings
                    allowed = negotiable.allowed_encodings
                    allowed_encodings = allowed
                    if allowed_encodings:
                        encodings = server.negotiate_forced_aspect(allowed,
                                                                   accepted)
                        encoding = (encodings and encodings[0]) or None

                allowed_languages = None
                language = self._language

                if not language:
                    accepted = request.accepted_languages
                    allowed = negotiable.allowed_languages
                    allowed_languages = allowed
                    if allowed:
                        languages = server.negotiate_forced_aspect(allowed,
                                                                   accepted)
                        language = (languages and languages[0]) or None

                if ((allowed_encodings and encoding is None)
                    or (allowed_languages and language is None)):
                        msg = ("None of the allowed encodings or "
                               "languages is accepted")
                        kwargs = {"allowed_encodings": allowed_encodings,
                                  "allowed_languages": allowed_languages}
                        raise http.NotAcceptableError(msg, **kwargs)

                if allowed_encodings:
                    self.set_encoding(encoding)

                if allowed_languages:
                    self.set_language(language)

            self.prepare()

            d = server.registry.write(self, obj, *args, **kwargs)
            d.addCallbacks(self._write_object_succeed,
                           self._write_object_failed,
                           callbackArgs=(obj, ))
            return d
        except:
            self._writing = False
            raise


    ### document.IWritableDocument ###

    def write(self, data):
        self._bytes += len(data)
        self.prepare()
        data = self._encode(data)
        if self._cache:
            self._cache.write(data)
        else:
            self._request._ref.write(data)

    def writelines(self, sequence):
        self.prepare()
        lines = [self._encode(l) for l in sequence]
        self._bytes += sum(len(l) for l in lines)
        if self._cache is not None:
            self._cache.writelines(lines)
        else:
            self._request._ref.writelines(lines)

    ### protected ###

    def _initialize(self):
        pass

    def _set_location(self, location):
        self._location = location

    def _try_reset(self):
        if self._cache:
            assert not self._writing, "Something would go bad"
            self._encoding = None
            self._mime_type = None
            self._language = None
            self._caching_policy = None
            self._expiration_policy = None
            self._prepared = False
            self._cache = StringIO()
            self._objects = []

    def _finish(self):
        if self._request.cancelled:
            return

        status = http.Status[self._request._ref.code].name
        elapsed = time.time() - self._request.received
        self._request.debug("Finishing the request. Status: %s. "
                            "Elapsed: %.2f s", status, elapsed)

        self._finished = time.time()
        try:
            if self._cache is not None:
                data = self._cache.getvalue()
                self.prepare()
                self._request._ref.write(self._encode(data))
        except http.HTTPError:
            pass
        except Exception, e:
            msg = "Exception while writing the response"
            error.handle_exception(self, e, msg)

        # Always try to finish

        if self._server.statistics:
            self._server.statistics.request_finished(self._request, self)

        try:
            self._request._ref.finish()
        except http.HTTPError:
            pass
        except Exception, e:
            msg = "Exception during response finalization"
            error.handle_exception(self, e, msg)

    ### private ###

    def _check_header_not_sent(self):
        if (self._cache is None) and self._prepared:
            raise AlreadyPreparedError("Response not cached "
                                       "and already prepared")

    def _get_preferred(self, values, default):
        if values and (len(values) > 0):
            keys = values.keys()
            keys.sort(key=values.get)
            preferred = keys[-1]
            if "*" in preferred:
                return default
            return preferred
        return default

    def _set_header(self, key, value):
        if isinstance(value, unicode):
            value = value.encode(http.HEADER_ENCODING)
        self._request._ref.setHeader(key, value)

    def _select_suitable_encoding(self):
        if not self._encoding:
            accepted = self._request.accepted_encodings
            selected = self._get_preferred(accepted, http.DEFAULT_ENCODING)
            selected = self.ENCODING_TRANSLATION.get(selected, selected)
            self._encoding = selected

    def _select_suitable_language(self):
        if not self._language:
            accepted = self._request.accepted_languages
            selected = self._get_preferred(accepted, http.DEFAULT_LANGUAGE)
            self._language = selected

    def _select_suitable_mime_type(self):
        if not self._mime_type:
            self._mime_type = http.DEFAULT_MIMETYPE
            accepted = self._request.accepted_mime_types
            selected = self._get_preferred(accepted, http.DEFAULT_MIMETYPE)
            self._mime_type = selected

    def _encode(self, value):
        if isinstance(value, unicode):
            self._select_suitable_encoding()
            try:
                return value.encode(self._encoding)
            except LookupError:
                self.info("Responding with NOT_ACCEPTABLE because of unknown"
                          " encoding requested: %s", self._encoding)
                raise http.NotAcceptableError()
        return value

    def _update_headers(self):
        if self._mime_type:
            value = self._mime_type.lower()
            if self._encoding:
                charset = compat.python2http(self._encoding.lower())
                if charset not in ["iso-8859-1", "us-ascii"]:
                    value += "; charset=" + charset
            self._set_header("content-type", value)
        if self._language:
            value = self._language.lower()
            if  value != "en":
                self._set_header("content-language", self._language.lower())
        if self._server.identity:
            self._set_header("server", self._server.identity)

    def _write_object_succeed(self, result, obj):
        self._objects.append(obj)
        self._writing = False
        return result

    def _write_object_failed(self, failure):
        self._writing = False
        message = failure.getErrorMessage()
        if failure.check(document.NoWriterFoundError):
            raise http.NotAcceptableError(message, cause=failure)
        if failure.check(document.WriteError):
            raise http.InternalServerError(message, cause=failure)
        return failure


class RootResourceWrapper(log.Logger):

    implements(resource.IResource)

    def __init__(self, server):
        log.Logger.__init__(self, server)
        self._server = server

    ### resource.IResource ###

    isLeaf = False

    def getChildWithDefault(self, name, request):
        # We want to handle every requests
        return self

    def putChild(self, path, child):
        # We do not expose static child addition
        raise http.NotImplementedError()

    def render(self, priv_request):
        return self._server._process_request(priv_request)


### private ###


_protocol_lookup = {"HTTP/1.0": http.Protocols.HTTP10,
                    "HTTP/1.1": http.Protocols.HTTP11}
