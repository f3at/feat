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

"""
This module defines a set of "effects" defining ways of retrieving values:

 - XXX_attr: retrieve the value of the attribute with specified name.

 - XXX_get: call the method with specified name passing a key.
"""

from feat.common import defer
from feat.models import reference


def local_ref(*parts):
    """
    Create a reference builder with specified base location.
    using getter.local_ref("some", "base") to get a value with key
    "toto" will gives reference.Local("some", "base", "toto")
    """

    def getter(_value, context, **_params):
        return reference.Local(*(parts + (context["key"], )))

    return getter


def source_get(method_name):
    """
    Creates a getter that will drop the current value,
    and call the source's method with specified name
    using the context's key as first argument.
    @param method_name: the name of a method belonging to the source.
    @type method_name: str
    """

    def getter(_value, context, **_params):
        method = getattr(context["model"].source, method_name)
        return _get(method, context["key"], (), {})

    return getter


def source_attr(attr_name):
    """
    Creates a getter that will drop the current value
    and retrieve the source's attribute with specified name.
    @param attr_name: the name of an attribute belonging to the source.
    @type attr_name: str
    """

    def getter(_value, context, **_params):
        value = getattr(context["model"].source, attr_name)
        return _attr(value)

    return getter


def model_get(method_name):
    """
    Creates a getter that will drop the current value,
    and call the model's method with specified name
    using the context's key as first argument.
    @param method_name: the name of a method belonging to the model.
    @type method_name: str
    """

    def getter(_value, context, **_params):
        method = getattr(context["model"], method_name)
        return _get(method, context["key"], (), {})

    return getter


def model_attr(attr_name):
    """
    Creates a getter that will drop the current value
    and retrieve the model's attribute with specified name.
    @param attr_name: the name of an attribute belonging to the model.
    @type attr_name: str
    """

    def getter(_value, context, **_params):
        value = getattr(context["model"], attr_name)
        return _attr(value)

    return getter


def action_get(method_name):
    """
    Creates a getter that will drop the current value,
    and call the action's method with specified name
    using the context's key as first argument.
    @param method_name: the name of a method belonging to the action.
    @type method_name: str
    """

    def getter(_value, context, **_params):
        method = getattr(context["action"], method_name)
        return _get(method, context["key"], (), {})

    return getter


def action_attr(attr_name):
    """
    Creates a getter that will drop the current value
    and retrieve the action's attribute with specified name.
    @param attr_name: the name of an attribute belonging to the action.
    @type attr_name: str
    """

    def getter(_value, context, **_params):
        value = getattr(context["action"], attr_name)
        return _attr(value)

    return getter


def view_get(method_name):
    """
    Creates a getter that will drop the current value,
    and call the view's method with specified name
    using the context's key as first argument.
    @param method_name: the name of a method belonging to the view.
    @type method_name: str
    """

    def getter(_value, context, **_params):
        method = getattr(context["view"], method_name)
        return _get(method, context["key"], (), {})

    return getter


def view_attr(attr_name):
    """
    Creates a getter that will drop the current value
    and retrieve the view's attribute with specified name.
    @param attr_name: the name of an attribute belonging to the view.
    @type attr_name: str
    """

    def getter(_value, context, **_params):
        value = getattr(context["view"], attr_name)
        return _attr(value)

    return getter


### private ###


def _get(method, key, args, kwargs):
    return defer.maybeDeferred(method, key, *args, **kwargs)


def _attr(value):
    return defer.succeed(value)
