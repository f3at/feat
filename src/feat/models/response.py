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

from zope.interface import implements

from feat.models import model, value, getter

from feat.models.interface import *


### effects factories ###


def created(message):
    """Create a Deleted response builder with specified message."""

    def effect(_value, _context, **_params):
        return Created(message)

    return effect


def deleted(message):
    """Create a Deleted response builder with specified message."""

    def effect(_value, _context, **_params):
        return Deleted(message)

    return effect


### classes ###


class Response(model.Model):

    implements(IResponse)

    model.identity("feat.response")
    model.attribute("message", value.String(),
                    getter.model_attr("message"))
    model.attribute("type", value.Enum(ResponseTypes),
                    getter.model_attr("response_type"))

    def __init__(self, response_type, message):
        model.Model.__init__(self, None)
        self._response_type = response_type
        self._message = unicode(message)

    @property
    def message(self):
        return self._message

    ### IResponse ###

    @property
    def response_type(self):
        return self._response_type


class Created(Response):

    model.identity("feat.response.created")

    def __init__(self, message):
        Response.__init__(self, ResponseTypes.created, message)


class Updated(Response):

    model.identity("feat.response.updated")

    def __init__(self, message):
        Response.__init__(self, ResponseTypes.updated, message)


class Deleted(Response):

    model.identity("feat.response.deleted")

    def __init__(self, message):
        Response.__init__(self, ResponseTypes.deleted, message)


class Accepted(Response):

    model.identity("feat.response.accepted")

    def __init__(self, message):
        Response.__init__(self, ResponseTypes.accepted, message)


class Done(Response):

    model.identity("feat.response.done")

    def __init__(self, message):
        Response.__init__(self, ResponseTypes.done, message)
