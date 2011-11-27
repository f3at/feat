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
import time

from twisted.internet import reactor, threads
from zope.interface import implements

from feat.common import defer, log
from feat.web import http, webserver

from feat.models.interface import ActionCategories, IActionPayload, IAspect
from feat.models.interface import IContext, IModel, IModelAction, IReference


class Context(object):

    __slots__ = ("scheme", "models", "names", "remaining")

    implements(IContext)

    default_actions = set([u"set", u"del", u"post"])

    def __init__(self, scheme, models, names, remaining=[]):
        self.scheme = scheme
        self.names = tuple(names)
        self.models = tuple(models)
        self.remaining = tuple(remaining)

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
        return http.compose(host=host, port=port,
                            path=path, scheme=self.scheme)

    def descend(self, model):
        remaining = self.remaining
        if self.remaining:
            if self.remaining[0] == model.name:
                remaining = self.remaining[1:]
        return Context(self.scheme,
                       self.models + (model, ),
                       self.names + (model.name, ),
                       remaining)


class ModelResource(webserver.BaseResource):

    __slots__ = ("model", "_methods", "_model_history", "_name_history")

    implements(webserver.IWebResource)

    action_methods = {u"set": http.Methods.PUT,
                      u"del": http.Methods.DELETE,
                      u"post": http.Methods.POST}
    method_actions = {http.Methods.DELETE: u"del",
                      http.Methods.PUT: u"set",
                      http.Methods.POST: u"post"}

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
        return d

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
            context = Context(request.scheme,
                              self._model_history,
                              self._name_history,
                              remaining[1:])
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

            context = Context(request.scheme,
                              self._model_history,
                              self._name_history)
            return ActionResource(action, context)

        if not remaining or (remaining == (u'', )):
            if self.model.reference is not None:
                return process_reference(self.model.reference)
            return self

        resource_name = remaining[0]

        if len(remaining) == 1:
            if resource_name.startswith('_'):
                return locate_action(resource_name[1:])
            action_name = self.method_actions.get(request.method)
            return locate_default_action(resource_name, action_name)

        return locate_model(resource_name)

    def action_GET(self, request, response, location):
        response.set_header("Cache-Control", "no-store")
        response.set_header("connection", "close")
        context = Context(request.scheme,
                          self._model_history, self._name_history)
        if location[-1] == u"":
            return self.render_action("get", request, response, context)
        return self.render_model(request, response, context)

    def render_action(self, action_name, request, response, context):

        def got_data(data):
            return response.write_object(data, context=context)

        def got_action(action):
            if action is None:
                return self.render_model(request, response, context)

            request.log("Performing action %r on %s model %r",
                        action_name, self.model.identity, self.model.name)
            d = action.perform()
            d.addCallback(got_data)
            return d

        d = self.model.fetch_action(action_name)
        d.addCallback(got_action)
        return d

    def render_model(self, request, response, context):
        return response.write_object(self.model, context=context)

    def render_error(self, request, response, error):
        response.force_mime_type("text/plain")
        return "ERROR " + type(error).__name__ + ": " + str(error)


class ActionResource(webserver.BaseResource):

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
                                          ActionCategories.command))}

    def __init__(self, action, context):
        self._action = IModelAction(action)
        self._context = context
        self._methods = set()
        self._update_methods(action, self._methods)

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
            response.set_header("Cache-Control", "no-store")
            response.set_header("connection", "close")
            return response.write_object(data, context=self._context)

        is_idempotent, categories = self.action_validation[request.method]
        if (self._action.is_idempotent not in is_idempotent
            or self._action.category not in categories):
            raise http.NotAllowedError(allowed_methods=list(self._methods))

        request.log("Performing action %r on %s model %r with parameters %r",
                    self._action.name, self._context.models[-1].identity,
                    self._context.models[-1].name, params)
        d = self._action.perform(**params)
        d.addCallback(got_data)
        return d

    def render_error(self, request, response, error):
        response.force_mime_type("text/plain")
        return "ERROR: " + str(error)

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


class StaticResource(webserver.BaseResource):

    BUFFER_SIZE = 1024*1024*4

    def __init__(self, root_path):
        webserver.BaseResource.__init__(self)
        if not os.path.isdir(root_path):
            raise ValueError("Invalid resource path: %r" % root_path)
        self._root_path = root_path
        self._mime_types = mimetypes.MimeTypes()

    def locate_resource(self, request, location, remaining):
        request.context["rel_loc"] = remaining
        return self

    def action_GET(self, request, response, location):
        rel_path = http.tuple2path(request.context["rel_loc"])
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
        response.set_header("connection", "close")
        if content_encoding is not None:
            response.set_header("content-encoding", content_encoding)

        try:
            res = open(res_path, "rb")
        except IOError:
            raise http.ForbiddenError()

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


class Root(ModelResource):
    """
    FIXME: The resource initiate itself the first time it is rendered
    or when locating children in a rather ugly way."""

    implements(IAspect)

    name = "root"
    label = "FEAT Gateway"
    desc = None

    def __init__(self, hostname, port, source, static_path):
        self.source = source
        self.hostname = hostname
        self.port = port
        self._initiating = True
        self._static = StaticResource(static_path)
        self._methods = set([http.Methods.GET])

    def locate_resource(self, request, location, remaining):

        def locate(_param):
            if remaining[0] == u"static":
                return self._static, remaining[1:]
            return ModelResource.locate_resource(self, request,
                                                 location, remaining)

        d = self.initiate()
        return d.addCallback(locate)

    def render_resource(self, request, response, location):
        d = self.initiate()
        d.addCallback(ModelResource.render_resource,
                      request, response, location)
        return d

    def initiate(self):
        if isinstance(self._initiating, defer.Deferred):
            d = defer.Deferred()
            self._initiating.addCallback(d.callback)
            self._initiating.addCallback(defer.override_result, self)
            return d

        if self._initiating is None:
            return defer.succeed(self)

        self._methods.clear()
        root = (self.hostname, self.port)
        ModelResource.__init__(self, self.source, root)
        d = self.model.initiate(aspect=self)
        d.addCallback(defer.drop_param, ModelResource.initiate, self)
        self._initiating = d
        d.addCallback(self._initiated)
        return d

    def _initiated(self, _param):
        self._initiating.addErrback(defer.handle_failure, "Failure during "
                                    "root resource initialization")
        self._initiating = None
        return self
