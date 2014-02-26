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

from feat.models.interface import IResponse, ResponseTypes
from feat.database.interface import IDocument

### effects factories ###


def created(message):
    """Create a Deleted response builder with specified message."""

    def create(value, _context, **_params):
        return Created(value, message)

    return create


def deleted(message):
    """Create a Deleted response builder with specified message."""

    def deleted(value, _context, **_params):
        return Deleted(value, message)

    return deleted


def done(message):
    """Create a Deleted response builder with specified message."""

    def done(value, _context, **_params):
        return Done(value, message)

    return done


def updated(message):

    def updated(value, _context, **_params):
        return Updated(message)

    return updated


### classes ###


class Response(model.Model):

    implements(IResponse)

    model.identity("feat.response")
    model.is_detached()
    model.attribute("message", value.String(),
                    getter.model_attr("source"))
    model.attribute("type", value.Enum(ResponseTypes),
                    getter.model_attr("_response_type"))
    model.attribute("id", value.String(),
                    getter.model_attr("id"))

    def __init__(self, response_type, message):
        self.id = None
        model.Model.__init__(self, message)
        self._response_type = response_type

    ### IResponse ###

    @property
    def response_type(self):
        return self._response_type


class Created(Response):

    model.identity("feat.response.created")

    def __init__(self, reference, message):
        Response.__init__(self, ResponseTypes.created, message)
        self.reference = reference if reference is not None else None
        if IDocument.providedBy(reference):
            self.id = reference.doc_id


class Updated(Response):

    model.identity("feat.response.updated")

    def __init__(self, message):
        Response.__init__(self, ResponseTypes.updated, message)


class Deleted(Response):

    model.identity("feat.response.deleted")

    def __init__(self, reference, message):
        Response.__init__(self, ResponseTypes.deleted, message)
        self.reference = reference if reference is not None else None


class Accepted(Response):

    model.identity("feat.response.accepted")

    def __init__(self, message):
        Response.__init__(self, ResponseTypes.accepted, message)


class Done(Response):

    model.identity("feat.response.done")

    def __init__(self, reference, message):
        Response.__init__(self, ResponseTypes.done, message)
        self.reference = reference if reference is not None else None
