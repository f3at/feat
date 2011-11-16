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

from twisted.internet import reactor, threads
from zope.interface import implements

from feat.common import defer, log
from feat.web import http, webserver

from feat.models.interface import *


class Context(object):

    implements(IContext)

    def __init__(self, scheme, names, models, remaining=[]):
        self.scheme = scheme
        self.names = tuple(names)
        self.models = tuple(models)
        self.remaining = tuple(remaining)

    def make_address(self, location):
        host, port = location[0]
        path = "/" + http.tuple2path(location[1:])
        return http.compose(host=host, port=port,
                            path=path, scheme=self.scheme)


class Resource(webserver.BaseResource):

    __slots__ = ("model", "history", "_methods")

    implements(webserver.IWebResource, IContext)

    def __init__(self, model, name=None, models=[], names=[]):
        self.model = IModel(model)
        self._model_history = list(models) + [self.model]
        self._name_history = list(names) + [name]
        self._methods = [] # [http.Methods]

    def initiate(self):
        """
        Initiate the resource retrieving all the asynchronous
        information needed to support the IWebResource interface.
        """

        def deduce_methods(actions):
            methods = set([http.Methods.GET])
            for action in actions:
                if not action.is_idempotent:
                    methods.add(http.Methods.POST)
                elif action.category is ActionCategory.delete:
                    methods.add(http.Methods.DELETE)
                elif action.category in (ActionCategory.create,
                                         ActionCategory.update):
                    methods.add(http.Methods.PUT)
                elif action.category is ActionCategory.command:
                    methods.add(http.Methods.POST)
            self._methods = methods

        d = self.model.fetch_actions()
        d.addCallback(deduce_methods)
        d.addCallback(defer.override_result, self)
        return d

    ### webserver.IWebResource ###

    @property
    def authenticator(self):
        return None

    @property
    def authorizer(self):
        return None

    def set_inherited(self, authenticator=None, authorizer=None):
        pass

    def is_method_allowed(self, request, location, methode):
        return methode in self._methods

    def get_allowed_methods(self, request, location):
        return list(self._methods)

    def locate_resource(self, request, location, remaining):

        def retrieve_model(item):
            if item is None:
                return None
            if remaining:
                return item.browse()
            return item.fetch()

        def create_resource(model, name):
            if model is None:
                # Document not found
                return None

            if IReference.providedBy(model):
                context = Context(request.scheme, self._name_history,
                                  self._model_history, remaining[1:])
                address = model.resolve(context)
                raise http.MovedPermanently(location=address)

            res = Resource(model, name,
                           self._model_history, self._name_history)
            return res.initiate(), remaining[1:]

        if not remaining or (remaining == (u'', )):
            return self

        name = remaining[0]
        d = self.model.fetch_item(name)
        d.addCallback(retrieve_model)
        d.addCallback(create_resource, name)
        return d

    def render_resource(self, request, response, location):
        response.set_header("Cache-Control", "no-store")
        response.set_header("connection", "close")
        context = Context(request.scheme, self._name_history,
                          self._model_history)
        if location[-1] == u"":
            return self.render_action("get", request, response, context)
        return self.render_model(request, response, context)

    def render_action(self, action_name, request, response, context):

        def got_data(data):
            return response.write_object(data, context=context)

        def got_action(action):
            if action is None:
                return self.render_model(request, response, context)

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
        return "ERROR: " + str(error)


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

        length = os.path.getsize(res_path)
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


class Root(Resource):

    def __init__(self, hostname, port, source, static_path):
        Resource.__init__(self, source, (hostname, port))
        self._static = StaticResource(static_path)

    def locate_resource(self, request, location, remaining):
        if remaining[0] == u"static":
            return self._static, remaining[1:]
        return Resource.locate_resource(self, request, location, remaining)
