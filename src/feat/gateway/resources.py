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

import mimetypes
import os
import sys
import time

from twisted.internet import reactor, threads
from zope.interface import implements

from feat.common import defer, error
from feat.web import http, webserver
from feat.models.model import DummyOfficer

from feat.models.interface import ActionCategories, IActionPayload, IAspect,\
    ValueTypes, IEncodingInfo
from feat.models.interface import IContext, IModel, IModelAction
from feat.models.interface import IAttribute, IReference
from feat.models.interface import ErrorTypes, IErrorPayload, Unauthorized
from feat.models.interface import ParameterError, InvalidParameters


class ErrorPayload(object):

    implements(IErrorPayload)

    @classmethod
    def from_exception(cls, ex):
        error_type = ErrorTypes.generic
        status_code = None
        error_code = None
        message = None
        subjects = None
        reasons = None
        debug = None
        trace = None

        if isinstance(ex, error.FeatError):
            error_code = ex.error_code
            message = ex.error_name

        if isinstance(ex, http.HTTPError):
            error_type = ErrorTypes.http
            status_code = ex.status_code
            if error_code is None:
                error_code = int(status_code)

        if isinstance(ex, ParameterError):
            error_type = ex.error_type
            status_code = http.Status.BAD_REQUEST
            subjects = ex.parameters
            if isinstance(ex, InvalidParameters):
                reasons = ex.reasons

        if not message:
            message = str(ex) or type(ex).__name__

        if not isinstance(ex, http.HTTPError):
            debug = str(ex)
            trace = error.get_exception_traceback(ex)

        return cls(error_type=error_type, error_code=error_code,
                   status_code=status_code, message=message,
                   subjects=subjects, reasons=reasons,
                   debug=debug, trace=trace)

    def __init__(self, error_type, error_code=None, status_code=None,
                 message=None, subjects=None, reasons=None,
                 debug=None, trace=None):

        def convert_value(value, converter):
            return converter(value) if value is not None else None

        def convert_list(values, converter):
            if values is None:
                return None
            return tuple([converter(v) for v in values])

        def convert_dict(items, kconv, vconv):
            if items is None:
                return None
            return dict((kconv(k), vconv(v)) for k, v in items.iteritems())

        self.error_type = ErrorTypes(error_type)
        self.error_code = convert_value(error_code, int)
        self.status_code = convert_value(status_code, http.Status)
        self.message = convert_value(message, unicode)
        self.subjects = convert_list(subjects, unicode)
        self.reasons = convert_dict(reasons, unicode, unicode)
        self.debug = convert_value(debug, unicode)
        self.trace = convert_value(trace, unicode)

    def __str__(self):
        msg = "ERROR"
        if self.error_code is not None:
            msg += " %d" % (self.error_code, )
        if self.message is not None:
            msg += ": %s" % (self.message, )
        if self.debug is not None:
            msg += "\n\n%s" % (self.debug, )
        if self.trace is not None:
            msg += "\n%s" % (self.trace, )
        return msg

    @property
    def stamp(self):
        return hex(id(self))


class Context(object):

    __slots__ = ("scheme", "models", "names", "remaining", "arguments")

    implements(IContext)

    default_actions = set([u"set", u"del", u"post"])

    def __init__(self, scheme, models, names, remaining=None, arguments=None):
        self.scheme = scheme
        self.names = tuple(names)
        self.models = tuple(models)
        self.remaining = tuple(remaining) if remaining else ()
        self.arguments = dict(arguments) if arguments else {}

    ### public ###

    def get_action_method(self, action):
        if not action.is_idempotent:
            return http.Methods.POST
        if action.category is ActionCategories.retrieve:
            return http.Methods.GET
        if action.category is ActionCategories.delete:
            return http.Methods.DELETE
        if action.category in (ActionCategories.create,
                               ActionCategories.update):
            return http.Methods.PUT
        return http.Methods.POST

    ### IContext ###

    def make_action_address(self, action):
        if action.name == u"get":
            return self.make_model_address(self.names + (u"", ))

        if action.name in self.default_actions:
            return self.make_model_address(self.names)

        action_ident = "_" + action.name
        return self.make_model_address(self.names + (action_ident, ))

    def make_model_address(self, location):
        host, port = location[0]
        path = "/" + http.tuple2path(location[1:])
        return http.compose(host=host, port=port, path=path,
                            query=http.compose_qs(self.arguments),
                            scheme=self.scheme)

    def descend(self, model):
        remaining = self.remaining
        if self.remaining:
            if self.remaining[0] == model.name:
                remaining = self.remaining[1:]
        return Context(scheme=self.scheme,
                       models=self.models + (model, ),
                       names=self.names + (model.name, ),
                       remaining=remaining,
                       arguments=self.arguments)


class BaseResource(webserver.BaseResource):

    def make_context(self, request):
        """Overridden in sub-classes."""

    def filter_errors(self, failure):
        failure.trap(Unauthorized)
        raise http.ForbiddenError, None, failure.tb

    def render_error(self, request, response, ex):

        def nice_error_failed(failure):
            if failure.check(http.NotAcceptableError):
                request.debug("Failed to negotiate a mime type to render the "
                              "error payload. Accepted mime types: %s. ",
                              request.accepted_mime_types)
            else:
                error.handle_failure(None, failure,
                                     "Failure during error rendering")
            # Do what we can...
            data = str(payload)
            if response.can_update_headers:
                response.force_mime_type("text/plain")
                response.set_length(len(data))
            return data

        payload = ErrorPayload.from_exception(ex)

        if not response.can_update_headers:
            return str(payload)

        response.set_header("Cache-Control", "no-cache")
        response.set_header("connection", "close")
        if payload.status_code is not None:
            response.set_status(payload.status_code)

        context = self.make_context(request)

        arguments = _validate_arguments(request.arguments)
        d = response.write_object(payload, context=context, **arguments)
        d.addErrback(nice_error_failed)
        return d


def _validate_arguments(arguments):
    # request parsers gives us correct dictionary key->[values],
    # which is compliant with www-urlencoding, although not very usefull
    return dict((k, v[0]) for k, v in arguments.iteritems())


class ActionResource(BaseResource):

    implements(webserver.IWebResource)

    # Use to validate action in function of the http method
    # the first tuple contains the valid values for is_idempotent
    # and the second the valid values for category.
    action_validation = {http.Methods.GET:
                         ((True, ), (ActionCategories.retrieve, )),
                         http.Methods.DELETE:
                         ((True, ), (ActionCategories.delete, )),
                         http.Methods.PUT:
                         ((True, ), (ActionCategories.create,
                                     ActionCategories.update)),
                         http.Methods.POST:
                         ((True, False), (ActionCategories.create,
                                          ActionCategories.update,
                                          ActionCategories.retrieve,
                                          ActionCategories.command))}

    def __init__(self, action, context):
        self._action = IModelAction(action)
        self._context = context
        self._methods = set()
        self._update_methods(action, self._methods)

    def make_context(self, request):
        return self._context

    ### webserver.IWebResource ###

    def is_method_allowed(self, request, location, methode):
        return methode in self._methods

    def get_allowed_methods(self, request, location):
        return list(self._methods)

    def locate_resource(self, request, location, remaining):
        raise NotImplementedError()

    @webserver.read_object(IActionPayload, {})
    def render_resource(self, params, request, response, location):

        def got_data(data):
            response.set_header("Cache-Control", "no-cache")

            if IEncodingInfo.providedBy(self._action.result_info):
                enc_info = IEncodingInfo(self._action.result_info)
                mime_type = enc_info.mime_type
                encoding = enc_info.encoding

                if mime_type:
                    request.debug("Changing mime_type to %r", mime_type)
                    response.set_mime_type(mime_type)
                if encoding:
                    request.debug("Changing encoding to %r", encoding)
                    response.set_encoding(encoding)

                response.set_length(len(data))
                return response.write(data)

            #FIXME: passing query arguments without validation is not safe
            return response.write_object(data, context=self._context,
                                         **request.arguments)

        is_idempotent, categories = self.action_validation[request.method]
        if (self._action.is_idempotent not in is_idempotent
            or self._action.category not in categories):
            raise http.NotAllowedError(allowed_methods=list(self._methods))

        # in case GET request to the ActionCategory.retrieve action,
        # the action parameters are in the query string, here we parse it
        request.debug("%r", self._action.category)
        if (self._action.category == ActionCategories.retrieve and
            self._action.is_idempotent and request.method == http.Methods.GET):
            params = dict()
            request.debug("%r", self._action.parameters)
            request.debug("%r", request.arguments)
            for param in self._action.parameters:
                if param.name in request.arguments:
                    if param.value_info.value_type == ValueTypes.collection:
                        params[param.name] = request.arguments[param.name]
                    else:
                        params[param.name] = request.arguments[param.name][0]

        # avoid putting lots of text into the log
        repr_params = repr(params)
        if len(repr_params) > 500:
            repr_params = repr_params[:500] + ' (truncated)'
        request.debug("Performing action %r on %s model %r with parameters %s",
                    self._action.name, self._context.models[-1].identity,
                    self._context.models[-1].name, repr_params)
        d = self._action.perform(**params)
        d.addCallback(got_data)
        d.addErrback(self.filter_errors)
        return d

    ### private ###

    def _update_methods(self, action, methods):
        if not action.is_idempotent:
            methods.add(http.Methods.POST)
        elif action.category is ActionCategories.delete:
            methods.add(http.Methods.DELETE)
        elif action.category in (ActionCategories.create,
                                 ActionCategories.update):
            methods.add(http.Methods.PUT)
            methods.add(http.Methods.POST)
        elif action.category is ActionCategories.command:
            methods.add(http.Methods.POST)


class ModelResource(BaseResource):

    __slots__ = ("model", "_methods", "_model_history", "_name_history")

    implements(webserver.IWebResource)

    action_methods = {u"set": http.Methods.PUT,
                      u"del": http.Methods.DELETE,
                      u"post": http.Methods.POST}
    method_actions = {http.Methods.DELETE: u"del",
                      http.Methods.PUT: u"set",
                      http.Methods.POST: u"post"}

    ActionResource = ActionResource

    def __init__(self, model, name=None, models=[], names=[]):
        self.model = IModel(model)
        self._model_history = list(models) + [self.model]
        self._name_history = list(names) + [name]
        self._methods = set([]) # set([http.Methods])

    def __repr__(self):
        return "<%s %s '%s'>" % (type(self).__name__,
                                 self.model.identity,
                                 self.model.name)

    def __str__(self):
        return repr(self)

    def initiate(self):
        """
        Initiate the resource retrieving all the asynchronous
        information needed to support the IWebResource interface.
        """

        def deduce_methods(actions):
            self._methods.add(http.Methods.GET)
            for action in actions:
                method = self.action_methods.get(action.name)
                if method is not None:
                    self._methods.add(method)

        d = self.model.fetch_actions()
        d.addCallback(deduce_methods)
        d.addCallback(defer.override_result, self)
        d.addErrback(self.filter_errors)
        return d

    def make_context(self, request, remaining=None):
        return Context(scheme=request.scheme,
                       models=self._model_history,
                       names=self._name_history,
                       remaining=remaining,
                       arguments=request.arguments)

    ### webserver.IWebResource ###

    def is_method_allowed(self, request, location, method):
        return method in self._methods

    def get_allowed_methods(self, request, location):
        return list(self._methods)

    def locate_resource(self, request, location, remaining):

        def locate_model(model_name):
            d = defer.succeed(self.model)
            d.addCallback(retrieve_model, model_name)
            d.addCallback(check_model)
            d.addCallback(wrap_model)
            return d

        def locate_action(action_name):
            d = defer.succeed(self.model)
            d.addCallback(retrieve_action, action_name)
            d.addCallback(wrap_action)
            return d

        def locate_default_action(model_name, action_name):
            d = defer.succeed(self.model)
            d.addCallback(retrieve_model, model_name)
            d.addCallback(check_model)
            d.addCallback(retrieve_action, action_name)
            d.addCallback(wrap_action, fallback=True)
            return d

        def retrieve_model(model, model_name):
            d = model.fetch_item(model_name)
            d.addCallback(got_model_item)
            return d

        def got_model_item(item):
            if item is None:
                raise http.NotFoundError()

            rem = remaining[1:]
            if rem and rem != (u"", ):
                return item.browse()

            return item.fetch()

        def check_model(model):
            if model is None:
                raise http.NotFoundError()

            if IReference.providedBy(model):
                return process_reference(model)

            if model.reference is not None:
                return process_reference(model.reference)

            return model

        def process_reference(reference):
            reference = IReference(reference)
            context = self.make_context(request, remaining[1:])
            address = reference.resolve(context)
            raise http.MovedPermanently(location=address)

        def wrap_model(model):
            if model is None:
                raise http.NotFoundError()

            res = ModelResource(model, model.name,
                                self._model_history, self._name_history)
            return res.initiate(), remaining[1:]

        def retrieve_action(model, action_name):
            d = model.fetch_action(action_name)
            d.addCallback(lambda a: (model, a))
            return d

        def wrap_action(model_action, fallback=False):
            model, action = model_action
            if action is None:
                if fallback:
                    return wrap_model(model)
                raise http.NotFoundError()

            context = self.make_context(request)
            return self.ActionResource(action, context)

        if not remaining or (remaining == (u'', )):
            if self.model.reference is not None:
                return process_reference(self.model.reference)
            return self

        resource_name = remaining[0]

        if len(remaining) == 1:
            if resource_name.startswith('_'):
                return locate_action(resource_name[1:])
            action_name = self.method_actions.get(request.method)
            d = locate_default_action(resource_name, action_name)
        else:
            d = locate_model(resource_name)

        d.addErrback(self.filter_errors)
        return d

    def action_GET(self, request, response, location):
        response.set_header("Cache-Control", "no-cache")
        context = self.make_context(request)
        if location[-1] == u"":
            return self.render_action("get", request, response, context)
        return self.render_model(self.model, request, response, context)

    def render_action(self, action_name, request, response, context):

        def got_data(data, action):
            result_info = action.result_info
            if result_info.value_type is ValueTypes.binary:
                return self.render_binary(data, request, response,
                                          context, action.result_info)

            #FIXME: passing query arguments without validation is not safe
            arguments = _validate_arguments(request.arguments)
            return response.write_object(data, context=context, **arguments)

        def got_action(action):
            if action is None:
                return self.render_model(self.model, request,
                                         response, context)

            request.debug("Performing action %r on %s model %r",
                          action_name, self.model.identity, self.model.name)
            d = action.perform()
            d.addCallback(got_data, action)
            d.addErrback(self.filter_errors)
            return d

        d = self.model.fetch_action(action_name)
        d.addCallback(got_action)
        d.addErrback(self.filter_errors)
        return d

    def render_model(self, model, request, response, context):
        request.debug("Rendering model, identity: %s name: %r",
                      model.identity, model.name)
        if IAttribute.providedBy(model):
            return self.render_attribute(model, request, response, context)

        arguments = _validate_arguments(request.arguments)
        d = response.write_object(self.model, context=context, **arguments)
        d.addErrback(self.filter_errors)
        return d

    def render_attribute(self, attr, request, response, context):
        if attr.value_info.value_type is ValueTypes.binary:
            if attr.is_readable:
                d = attr.fetch_value()
                d.addCallback(self.render_binary, request, response,
                              context, attr.value_info)
                return d

        #FIXME: passing query arguments without validation is not safe
        arguments = _validate_arguments(request.arguments)
        d = response.write_object(attr, context=context, **arguments)
        d.addErrback(self.filter_errors)
        return d

    def render_binary(self, value, request, response, context, value_info):
        mime_type = None
        encoding = None
        if IEncodingInfo.providedBy(value_info):
            enc_info = IEncodingInfo(value_info)
            mime_type = enc_info.mime_type
            encoding = enc_info.encoding
        mime_type = mime_type or "application/octet-stream"
        response.set_mime_type(mime_type)
        if encoding:
            response.set_encoding(encoding)
        if value:
            response.set_length(len(value))
            response.write(value)
        else:
            response.set_length(0)


class StaticResource(BaseResource):

    BUFFER_SIZE = 1024*1024*4

    def __init__(self, hostname, port, root_path):
        webserver.BaseResource.__init__(self)
        if not os.path.isdir(root_path):
            raise ValueError("Invalid resource path: %r" % root_path)
        self._hostname = hostname
        self._port = port
        self._root_path = root_path
        self._mime_types = mimetypes.MimeTypes()

    def make_context(self, request):
        #FIXME: this is wrong, root should be separated from models and names
        return Context(scheme=request.scheme,
                       models=(None, ),
                       names=((self._hostname, self._port), ),
                       arguments=request.arguments)

    def locate_resource(self, request, location, remaining):
        if not remaining or remaining == (u"", ):
            return None
        request.context["rel_loc"] = remaining
        return self

    def action_GET(self, request, response, location):
        rel_loc = request.context.get("rel_loc")
        if rel_loc is None:
            raise http.NotFoundError()

        rel_path = http.tuple2path(rel_loc)
        full_path = os.path.join(self._root_path, rel_path)
        res_path = os.path.realpath(full_path)
        if not res_path.startswith(self._root_path):
            raise http.ForbiddenError()
        if os.path.isdir(res_path):
            raise http.ForbiddenError()
        if not os.path.isfile(res_path):
            raise http.NotFoundError()

        rst = os.stat(res_path)

        # FIXME: Caching Policy, should be extracted to a ICachingPolicy
        cache_control_header = request.get_header("cache-control") or ""
        pragma_header = request.get_header("pragma") or ""
        cache_control = http.parse_header_values(cache_control_header)
        pragma = http.parse_header_values(pragma_header)
        if not (u"no-cache" in cache_control or u"no-cache" in pragma):
            if u"max-age" in cache_control:
                max_age = int(cache_control[u"max-age"])
                if max_age == 0 or (time.time() - rst.st_mtime) < max_age:
                    response.set_status(http.Status.NOT_MODIFIED)
                    return

        length = rst.st_size
        mime_type, content_encoding = self._mime_types.guess_type(res_path)
        mime_type = mime_type or "application/octet-stream"

        response.set_length(length)
        response.set_mime_type(mime_type)

        if content_encoding is not None:
            response.set_header("content-encoding", content_encoding)

        try:
            res = open(res_path, "rb")
        except IOError:
            raise http.ForbiddenError(), None, sys.exc_info()[2]

        response.do_not_cache()

        return threads.deferToThread(self._write_resource, #@UndefinedVariable
                                     response, res)

    ### private ###

    def _write_resource(self, response, res):

        try:
            while True:
                data = res.read(self.BUFFER_SIZE)
                if not data:
                    break
                reactor.callFromThread(response.write, #@UndefinedVariable
                                       data)
        finally:
            res.close()


class Redirect(webserver.LeafResourceMixin):

    def __init__(self, location):
        self.location = location

    def render_resource(self, request, response, location):
        response.set_status(http.Status.MOVED_PERMANENTLY)
        response.set_header('Location', self.location)


class Root(BaseResource):

    implements(IAspect)

    name = "root"
    label = "FEAT Gateway"
    desc = None

    def __init__(self, hostname, port, source, label=None, static_path=None):
        self.source = source
        self.hostname = hostname
        self.port = port
        if label:
            self.label = label
        self._static = (static_path and
                        StaticResource(hostname, port, static_path))
        self._methods = set([http.Methods.GET])

    def locate_resource(self, request, location, remaining):
        request_host = request.get_header('host')
        if request_host is not None:
            if ':' in request_host:
                request_host = request_host.split(":", 1)[0]
            if request_host != self.hostname:
                new_uri = "%s://%s:%s%s" % (
                    request.scheme.name.lower(),
                    self.hostname,
                    self.port,
                    http.tuple2path(location + remaining))
                return Redirect(new_uri)

        if self._static and remaining[0] == u"static":
            return self._static, remaining[1:]

        return self._build_root(request), remaining

    ### private ###

    def _build_root(self, request):
        root = (self.hostname, self.port)
        model = IModel(self.source)
        officer = DummyOfficer(request.peer_info)

        d = defer.succeed(None)
        d.addCallback(defer.drop_param, model.initiate,
                      aspect=self, officer=officer)
        d.addCallback(ModelResource, root)
        d.addCallback(ModelResource.initiate)
        d.addErrback(self.filter_errors)
        return d
