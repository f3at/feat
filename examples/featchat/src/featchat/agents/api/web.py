# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

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
from zope.interface import implements, classProvides

from feat.agents.base import replay
from feat.common import serialization, log
from feat.web import webserver, http

from featchat.application import featchat

from featchat.agents.api.interface import IServer, IServerFactory, IWebAgent


@featchat.register_restorator
class ServerWrapper(serialization.Serializable):

    implements(IServer)
    classProvides(IServerFactory)

    def __init__(self, agent, port_number):
        agent = IWebAgent(agent)
        self._serializer = serialization.json.Serializer(force_unicode=True)
        self._root = Api(agent, self._serializer)
        self._server = webserver.Server(port_number, self._root)

    @replay.side_effect
    def start(self):
        self._server.initiate()

    @property
    def listening_port(self):
        return self._server.port

    def stop(self):
        self._server.cleanup()

    def __eq__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return True

    def __ne__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return False


@featchat.register_restorator
class ServerDummy(serialization.Serializable):

    implements(IServer)
    classProvides(IServerFactory)

    def __init__(self, agent, port_number):
        self.port_number = port_number

    @replay.side_effect
    def start(self):
        pass

    def stop(self):
        pass

    def __eq__(self, other):
        return self.port_number == other.port_number

    def __ne__(self, other):
        return not self.__eq__(other)


class BaseResource(webserver.BasicResource):

    def __init__(self, agent, serializer):
        self._agent = IWebAgent(agent)
        self._serializer = serializer
        webserver.BasicResource.__init__(self)

    def finish_request(self, response_data, response):
        resp, code = response_data

        response.set_status(code)
        response.write(resp)

    def done(self, result, code=http.Status.OK):
        return self._serializer.convert(result), code

    def error(self, error, code=http.Status.NOT_FOUND):
        log.log('web-hapi', error)
        return self._serializer.convert(error), code


class Api(BaseResource):

    def __init__(self, agent, serializer):
        BaseResource.__init__(self, agent, serializer)
        self['rooms'] = Rooms(agent, serializer)


class Rooms(BaseResource):

    def locate_child(self, request, location, remaining):
        name = remaining[0]
        return Room(self._agent, self._serializer, name)

    def action_GET(self, request, response, location):
        d = self._agent.get_room_list()
        d.addCallbacks(self.done, self.error)
        d.addCallback(self.finish_request, response)
        return d


class Room(BaseResource):

    def __init__(self, agent, serializer, name):
        BaseResource.__init__(self, agent, serializer)
        self._name = name

    def action_GET(self, request, response, location):
        d = self._agent.get_list_for_room(self._name)
        d.addCallbacks(self.done, self.error)
        d.addCallback(self.finish_request, response)
        return d

    def action_POST(self, request, response, location):
        d = self._agent.get_url_for_room(self._name)
        d.addCallbacks(self.done, self.error)
        d.addCallback(self.finish_request, response)
        return d
