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

 - XXX_getattr: get the attribute with name given by the context's key.

"""

from feat.common import defer


def source_get(method_name):
    """
    Creates a getter that will drop the current value,
    and call the source's method with specified name
    using the context's key as first argument.
    @param method_name: the name of a method belonging to the source.
    @type method_name: str
    """

    def source_get(_value, context, **_params):
        method = getattr(context["model"].source, method_name)
        return _get(method, context["key"], (), {})

    return source_get


def source_attr(attr_name):
    """
    Creates a getter that will drop the current value
    and retrieve the source's attribute with specified name.
    @param attr_name: the name of an attribute belonging to the source.
    @type attr_name: str
    """

    def source_attr(_value, context, **_params):
        value = getattr(context["model"].source, attr_name)
        return _attr(value)

    return source_attr


def source_getattr():
    """
    Creates a getter that will drop the current value
    and retrieve the source's attribute with the context key as name.
    """

    def source_getattr(_value, context, **_params):
        value = getattr(context["model"].source, context["key"])
        return _attr(value)

    return source_getattr


def source_list_names(attr_name):

    def source_list_names(_value, context, **_params):
        value = getattr(context["model"].source, attr_name)
        if not isinstance(value, list):
            raise ValueError("Expected a list, got %r" % (value, ))
        return _attr(map(str, range(len(value))))

    return source_list_names


def source_list_get(attr_name):

    def source_list_get(_value, context, **_params):
        list_ = getattr(context["model"].source, attr_name)
        if not isinstance(list_, list):
            raise ValueError("Expected a list, got %r" % (list_, ))
        return _attr(list_[int(context["key"])])

    return source_list_get


def model_get(method_name):
    """
    Creates a getter that will drop the current value,
    and call the model's method with specified name
    using the context's key as first argument.
    @param method_name: the name of a method belonging to the model.
    @type method_name: str
    """

    def model_get(_value, context, **_params):
        method = getattr(context["model"], method_name)
        return _get(method, context["key"], (), {})

    return model_get


def model_attr(attr_name):
    """
    Creates a getter that will drop the current value
    and retrieve the model's attribute with specified name.
    @param attr_name: the name of an attribute belonging to the model.
    @type attr_name: str
    """

    def model_attr(_value, context, **_params):
        value = getattr(context["model"], attr_name)
        return _attr(value)

    return model_attr


def model_getattr():
    """
    Creates a getter that will drop the current value
    and retrieve the model's attribute with the context key as name.
    """

    def model_getattr(_value, context, **_params):
        value = getattr(context["model"], context["key"])
        return _attr(value)

    return model_getattr


def action_get(method_name):
    """
    Creates a getter that will drop the current value,
    and call the action's method with specified name
    using the context's key as first argument.
    @param method_name: the name of a method belonging to the action.
    @type method_name: str
    """

    def action_get(_value, context, **_params):
        method = getattr(context["action"], method_name)
        return _get(method, context["key"], (), {})

    return action_get


def action_attr(attr_name):
    """
    Creates a getter that will drop the current value
    and retrieve the action's attribute with specified name.
    @param attr_name: the name of an attribute belonging to the action.
    @type attr_name: str
    """

    def action_attr(_value, context, **_params):
        value = getattr(context["action"], attr_name)
        return _attr(value)

    return action_attr


def action_getattr():
    """
    Creates a getter that will drop the current value
    and retrieve the action's attribute with the context key as name.
    """

    def action_getattr(_value, context, **_params):
        value = getattr(context["action"], context["key"])
        return _attr(value)

    return action_getattr


def view_get(method_name):
    """
    Creates a getter that will drop the current value,
    and call the view's method with specified name
    using the context's key as first argument.
    @param method_name: the name of a method belonging to the view.
    @type method_name: str
    """

    def view_get(_value, context, **_params):
        method = getattr(context["view"], method_name)
        return _get(method, context["key"], (), {})

    return view_get


def view_attr(attr_name):
    """
    Creates a getter that will drop the current value
    and retrieve the view's attribute with specified name.
    @param attr_name: the name of an attribute belonging to the view.
    @type attr_name: str
    """

    def view_attr(_value, context, **_params):
        value = getattr(context["view"], attr_name)
        return _attr(value)

    return view_attr


def view_getattr():
    """
    Creates a getter that will drop the current value
    and retrieve the source's attribute with the context key as name.
    """

    def view_getattr(_value, context, **_params):
        value = getattr(context["view"], context["key"])
        return _attr(value)

    return view_getattr


def value_get(method_name):
    """
    Creates a getter that will call value's method with specified name
    using the context's key as first argument.
    @param method_name: the name of a method belonging to the value.
    @type method_name: str
    """

    def value_get(value, context, **_params):
        method = getattr(value, method_name)
        return _get(method, context["key"], (), {})

    return value_get


def value_attr(attr_name):
    """
    Creates a getter that will retrieve value's attribute
    with specified name.
    @param attr_name: the name of an attribute belonging to the value.
    @type attr_name: str
    """

    def value_attr(value, context, **_params):
        value = getattr(value, attr_name)
        return _attr(value)

    return value_attr


def value_getattr():
    """
    Creates a getter that will retrieve the value's attribute
    with the context key as name.
    """

    def value_getattr(value, context, **_params):
        value = getattr(value, context["key"])
        return _attr(value)

    return source_getattr


### private ###


def _get(method, key, args, kwargs):
    return defer.maybeDeferred(method, key, *args, **kwargs)


def _attr(value):
    return defer.succeed(value)
