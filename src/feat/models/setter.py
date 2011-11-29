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
This module defines a set of "effects" defining ways of setting values:

 - XXX_attr: set the value of the attribute with specified name.

 - XXX_set: call the method with specified name passing
            a key and the new value.
"""

from feat.common import defer


def source_set(method_name):
    """
    Creates a setter that will call the source method with the context's
    key as first parameter and the value as second parameter.
    @param method_name: the name of a method belonging to the source.
    @type method_name: str
    """

    def source_set(value, context, **_params):
        method = getattr(context["model"].source, method_name)
        return _set(method, context["key"], value, (), {})

    return source_set


def source_attr(attr_name):
    """
    Creates a setter that will set the specified source attribute
    to the current value.
    @param attr_name: the name of an attribute belonging to the source.
    @type attr_name: str
    """

    def source_attr(value, context, **_params):
        setattr(context["model"].source, attr_name, value)
        return _attr()

    return source_attr


def source_setattr():
    """
    Creates a setter that will set the source attribute with context's key
    for name to the current value.
    """

    def source_setattr(value, context, **_params):
        setattr(context["model"].source, context["key"], value)
        return _attr()

    return source_setattr


def model_set(method_name):
    """
    Creates a setter that will call the model method with the context's
    key as first parameter and the value as second parameter.
    @param method_name: the name of a method belonging to the model.
    @type method_name: str
    """

    def model_set(value, context, **_params):
        method = getattr(context["model"], method_name)
        return _set(method, context["key"], value, (), {})

    return model_set


def model_attr(attr_name):
    """
    Creates a setter that will set the specified model attribute
    to the current value.
    @param attr_name: the name of an attribute belonging to the model.
    @type attr_name: str
    """

    def model_attr(value, context, **_params):
        setattr(context["model"], attr_name, value)
        return _attr()

    return model_attr


def model_setattr():
    """
    Creates a setter that will set the model attribute with context's key
    for name to the current value.
    """

    def model_setattr(value, context, **_params):
        setattr(context["model"], context["key"], value)
        return _attr()

    return model_setattr


def action_set(method_name):
    """
    Creates a setter that will call the action method with the context's
    key as first parameter and the value as second parameter.
    @param method_name: the name of a method belonging to the action.
    @type method_name: str
    """

    def action_set(value, context, **_params):
        method = getattr(context["action"], method_name)
        return _set(method, context["key"], value, (), {})

    return action_set


def action_attr(attr_name):
    """
    Creates a setter that will set the specified action attribute
    to the current value.
    @param attr_name: the name of an attribute belonging to the action.
    @type attr_name: str
    """

    def action_attr(value, context, **_params):
        setattr(context["action"], attr_name, value)
        return _attr()

    return action_attr


def action_setattr():
    """
    Creates a setter that will set the action attribute with context's key
    for name to the current value.
    """

    def action_setattr(value, context, **_params):
        setattr(context["action"], context["key"], value)
        return _attr()

    return action_setattr


def view_set(method_name):
    """
    Creates a setter that will call the view method with the context's
    key as first parameter and the value as second parameter.
    @param method_name: the name of a method belonging to the view.
    @type method_name: str
    """

    def view_set(value, context, **_params):
        method = getattr(context["view"], method_name)
        return _set(method, context["key"], value, (), {})

    return view_set


def view_attr(attr_name):
    """
    Creates a setter that will set the specified view attribute
    to the current value.
    @param attr_name: the name of an attribute belonging to the view.
    @type attr_name: str
    """

    def view_attr(value, context, **_params):
        setattr(context["view"], attr_name, value)
        return _attr()

    return view_attr


def view_setattr():
    """
    Creates a setter that will set the view attribute with context's key
    for name to the current value.
    """

    def view_setattr(value, context, **_params):
        setattr(context["view"], context["key"], value)
        return _attr()

    return view_setattr


### private ###


def _set(method, key, value, args, kwargs):
    return defer.maybeDeferred(method, key, value, *args, **kwargs)


def _attr():
    return defer.succeed(None)
