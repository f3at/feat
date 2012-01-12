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
This module defines a set of "effects" factories defining ways
of calling methods in a processing chain:

 - XXX_call: call a method with specified arguments and keywords dropping
             the current value and returning a new one asynchronously.

 - XXX_filter: call a method with the current value alongside specified
               arguments and keywords and returning a new one asynchronously.

 - XXX_perform: same as XXX_filter effects but dynamic parameters
                most probably from an action are added to the specified
                keywords.

"""

import inspect
import types

from feat.common import defer


def source_call(method_name, *args, **kwargs):
    """
    Creates an effect that will drop the current effect value,
    call the source's method with specified name
    with the specified arguments and keywords.
    @param method_name: the name of method belonging to the source reference.
    @type method_name: str
    """

    def source_call(_value, context, **_params):
        method = getattr(context["model"].source, method_name)
        return _call(method, args, kwargs)

    return source_call


def source_filter(method_name, *args, **kwargs):
    """
    Creates an effect that will call the source's method with the current
    value and specified arguments and keywords.
    @param method_name: the name of method belonging to the source reference.
    @type method_name: str
    """

    def source_filter(value, context, **_params):
        method = getattr(context["model"].source, method_name)
        return _filter(method, value, args, kwargs)

    return source_filter


def source_perform(method_name, *args, **kwargs):
    """
    Creates an effect that will call the source's method with the current
    value and specified arguments and the union of effect parameters and
    specified keywords (action's parameters take precedence).
    @param method_name: the name of method belonging to the source reference.
    @type method_name: str
    """

    def source_perform(value, context, **params):
        method = getattr(context["model"].source, method_name)
        return _perform(method, value, params, args, kwargs)

    return source_perform


def model_call(method_name, *args, **kwargs):
    """
    Creates an effect that will drop the current effect value,
    call the model's method with specified name
    with the specified arguments and keywords.
    @param method_name: the name of method belonging to the model.
    @type method_name: str
    """

    def model_call(_value, context, **_params):
        method = getattr(context["model"], method_name)
        return _call(method, args, kwargs)

    return model_call


def model_filter(method_name, *args, **kwargs):
    """
    Creates an effect that will call the model's method with the current
    value and specified arguments and keywords.
    @param method_name: the name of method belonging to the model.
    @type method_name: str
    """

    def model_filter(value, context, **_params):
        method = getattr(context["model"], method_name)
        return _filter(method, value, args, kwargs)

    return model_filter


def model_perform(method_name, *args, **kwargs):
    """
    Creates an effect that will call the model's method with the current
    value and specified arguments and the union of effect parameters and
    specified keywords (action's parameters take precedence).
    @param method_name: the name of method belonging to the model reference.
    @type method_name: str
    """

    def model_perform(value, context, **params):
        method = getattr(context["model"], method_name)
        return _perform(method, value, params, args, kwargs)

    return model_perform


def action_call(method_name, *args, **kwargs):
    """
    Creates an effect that will drop the current effect value,
    call the action's method with specified name
    with the specified arguments and keywords.
    @param method_name: the name of method belonging to the action.
    @type method_name: str
    """

    def action_call(_value, context, **_params):
        method = getattr(context["action"], method_name)
        return _call(method, args, kwargs)

    return action_call


def action_filter(method_name, *args, **kwargs):
    """
    Creates an effect that will call the action's method with the current
    value and specified arguments and keywords.
    @param method_name: the name of method belonging to the action.
    @type method_name: str
    """

    def action_filter(value, context, **_params):
        method = getattr(context["action"], method_name)
        return _filter(method, value, args, kwargs)

    return action_filter


def action_perform(method_name, *args, **kwargs):
    """
    Creates an effect that will call the action's method with the current
    value and specified arguments and the union of effect parameters and
    specified keywords (action's parameters take precedence).
    @param method_name: the name of method belonging to the action.
    @type method_name: str
    """

    def action_perform(value, context, **params):
        method = getattr(context["action"], method_name)
        return _perform(method, value, params, args, kwargs)

    return action_perform


def view_call(method_name, *args, **kwargs):
    """
    Creates an effect that will drop the current effect value,
    call the view's method with specified name
    with the specified arguments and keywords.
    @param method_name: the name of method belonging to the view.
    @type method_name: str
    """

    def view_call(_value, context, **_params):
        method = getattr(context["view"], method_name)
        return _call(method, args, kwargs)

    return view_call


def view_filter(method_name, *args, **kwargs):
    """
    Creates an effect that will call the view's method with the current
    value and specified arguments and keywords.
    @param method_name: the name of method belonging to the view.
    @type method_name: str
    """

    def view_filter(value, context, **_params):
        method = getattr(context["view"], method_name)
        return _filter(method, value, args, kwargs)

    return view_filter


def view_perform(method_name, *args, **kwargs):
    """
    Creates an effect that will call the view's method with the current
    value and specified arguments and the union of effect parameters and
    specified keywords (action's parameters take precedence).
    @param method_name: the name of method belonging to the view reference.
    @type method_name: str
    """

    def view_perform(value, context, **params):
        method = getattr(context["view"], method_name)
        return _perform(method, value, params, args, kwargs)

    return view_perform


def value_call(method_name, *args, **kwargs):
    """
    Creates an effect that will call value's method with specified name
    with the specified arguments and keywords.
    @param method_name: the name of method belonging to the value.
    @type method_name: str
    """

    def value_call(value, context, **_params):
        method = getattr(value, method_name)
        return _call(method, args, kwargs)

    return value_call


### private ###


def _call(method, args, kwargs):
    return defer.maybeDeferred(method, *args, **kwargs)


def _filter(method, value, args, kwargs):
    return defer.maybeDeferred(method, value, *args, **kwargs)


def _perform(method, value, params, args, kwargs):
    keywords = dict(kwargs)
    keywords.update(params)
    keywords["value"] = value
    arguments = []

    func = method

    if isinstance(method, types.MethodType):
        func = method.im_func

    if hasattr(func, 'original_func'):
        func = func.original_func

    argspec = inspect.getargspec(func)

    for name in argspec.args:
        if name in ("self"):
            continue
        if name not in keywords:
            break
        arguments.append(keywords.pop(name))

    arguments.extend(args)

    if not argspec.keywords:
        expected = set(argspec.args)
        for name in keywords.keys():
            if name not in expected:
                del keywords[name]

    return defer.maybeDeferred(method, *arguments, **keywords)
