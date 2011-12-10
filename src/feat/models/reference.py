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

from feat.models import meta as models_meta

from feat.models.interface import *


meta = models_meta.meta


class Reference(models_meta.Metadata):
    """Base class for references.
    @see: feat.models.interface.IReference"""

    implements(IReference)

    ### IReference ###

    def resolve(self, context):
        """Overridden in child classes."""


class Relative(Reference):

    implements(IRelativeReference)

    _base = None
    _location = None

    def __init__(self, *location, **kwargs):
        """
        Construct a relative reference.
        Arguments are the location parts and and optional keyword
        argument "base" can be given to specify from witch model
        with specified identity the location should start from.
        """
        self._base = unicode(kwargs["base"]) if "base" in kwargs else None
        self._location = tuple([unicode(i) for i in location])

    ### IReference ###

    def resolve(self, context):
        context = IContext(context)
        location = list(context.names)

        if self._base is not None:
            for model in reversed(context.models):
                if IModel(model).identity == self._base:
                    break
                location = location[:-1]
            else:
                raise BadReference("Base model %s not found in context"
                                   % (self._base, ))

        resolved = tuple(location) + self._location + context.remaining
        return context.make_model_address(resolved)

    ### IRelativeReference ###

    @property
    def base(self):
        return self._base

    @property
    def location(self):
        return self._location


class Action(Reference):

    def __init__(self, action):
        self._action = IModelAction(action)

    ### IReference ###

    def resolve(self, context):
        return context.make_action_address(self._action)


class Local(Reference):

    implements(ILocalReference)

    _location = None

    def __init__(self, *location):
        self._location = tuple([unicode(i) for i in location])

    ### IReference ###

    def resolve(self, context):
        context = IContext(context)
        resolved = context.names[:1] + self._location + context.remaining
        return context.make_model_address(resolved)

    ### ILocalReference ###

    @property
    def location(self):
        return self._location


class ExternalURL(Reference):

    def __init__(self, url):
        self._url = url

    def resolve(self, context):
        return self._url


class Absolute(Reference):

    implements(IAbsoluteReference)

    _root = None
    _location = None

    def __init__(self, root=None, *location):
        self._root = root
        self._location = tuple([unicode(i) for i in location])

    ### IReference ###

    def resolve(self, context):
        context = IContext(context)
        resolved = (self._root, ) + self._location + context.remaining
        return context.make_model_address(resolved)

    ### IReference ###

    @property
    def root(self):
        return self._root

    @property
    def location(self):
        return self._location
