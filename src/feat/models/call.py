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

In addition the module provides utility effects:

 - delay: perform the specified effect outside the execution chain after
          the specified time returning specified result right away.

EFFECT DEFINITION:

Effects are standardized callable with known parameters that can perform
different actions.

Effects' first argument is the current value in a processing chain.

Effect's second argument is the current context, a dictionary
containing the following keys when meaningful:

  - model: the current model.
  - view: the current view.
  - action: the current action.
  - key: the current key.

Effect's keywords arguments are extra dynamic parameters
that could be used by the effect, usually action parameters.

Effect's result is ALWAYSa defer.Deffered() instance fired
with the new value of the processing chain.
"""

import inspect

from feat.common import defer, time


def delay(effect, result=None, delay=0.001):
    """
    Creates and effect that will delays the execution
    of the specified effect and return the specified result right away.
    @param effect: the effect to delay.
    @type effect: callable
    @param result: the value to return right away.
    @type result: Any
    @param delay: the time to wait before performing
                  the specified effect in seconds.
    @type delay: float
    @return: a new effect that will delay the specified effect.
    @rtype: callable
    """

    def new_effect(value, context, **params):
        d = defer.Deferred()
        d.addCallback(effect, context, **params)
        time.call_next(d.callback, value)
        return result

    return new_effect


def source_call(method_name, *args, **kwargs):
    """
    Creates an effect that will drop the current effect value,
    call the source's method with specified name
    with the specified arguments and keywords.
    @param method_name: the name of method belonging to the source reference.
    @type method_name: str
    """

    def effect(_value, context, **_params):
        method = getattr(context["model"].source, method_name)
        return _call(method, args, kwargs)

    return effect


def source_filter(method_name, *args, **kwargs):
    """
    Creates an effect that will call the source's method with the current
    value and specified arguments and keywords.
    @param method_name: the name of method belonging to the source reference.
    @type method_name: str
    """

    def effect(value, context, **_params):
        method = getattr(context["model"].source, method_name)
        return _filter(method, value, args, kwargs)

    return effect


def source_perform(method_name, *args, **kwargs):
    """
    Creates an effect that will call the source's method with the current
    value and specified arguments and the union of effect parameters and
    specified keywords (action's parameters take precedence).
    @param method_name: the name of method belonging to the source reference.
    @type method_name: str
    """

    def effect(value, context, **params):
        method = getattr(context["model"].source, method_name)
        return _perform(method, value, params, args, kwargs)

    return effect


def model_call(method_name, *args, **kwargs):
    """
    Creates an effect that will drop the current effect value,
    call the model's method with specified name
    with the specified arguments and keywords.
    @param method_name: the name of method belonging to the model.
    @type method_name: str
    """

    def effect(_value, context, **_params):
        method = getattr(context["model"], method_name)
        return _call(method, args, kwargs)

    return effect


def model_filter(method_name, *args, **kwargs):
    """
    Creates an effect that will call the model's method with the current
    value and specified arguments and keywords.
    @param method_name: the name of method belonging to the model.
    @type method_name: str
    """

    def effect(value, context, **_params):
        method = getattr(context["model"], method_name)
        return _filter(method, value, args, kwargs)

    return effect


def model_perform(method_name, *args, **kwargs):
    """
    Creates an effect that will call the model's method with the current
    value and specified arguments and the union of effect parameters and
    specified keywords (action's parameters take precedence).
    @param method_name: the name of method belonging to the model reference.
    @type method_name: str
    """

    def effect(value, context, **params):
        method = getattr(context["model"], method_name)
        return _perform(method, value, params, args, kwargs)

    return effect


def action_call(method_name, *args, **kwargs):
    """
    Creates an effect that will drop the current effect value,
    call the action's method with specified name
    with the specified arguments and keywords.
    @param method_name: the name of method belonging to the action.
    @type method_name: str
    """

    def effect(_value, context, **_params):
        method = getattr(context["action"], method_name)
        return _call(method, args, kwargs)

    return effect


def action_filter(method_name, *args, **kwargs):
    """
    Creates an effect that will call the action's method with the current
    value and specified arguments and keywords.
    @param method_name: the name of method belonging to the action.
    @type method_name: str
    """

    def effect(value, context, **_params):
        method = getattr(context["action"], method_name)
        return _filter(method, value, args, kwargs)

    return effect


def action_perform(method_name, *args, **kwargs):
    """
    Creates an effect that will call the action's method with the current
    value and specified arguments and the union of effect parameters and
    specified keywords (action's parameters take precedence).
    @param method_name: the name of method belonging to the action.
    @type method_name: str
    """

    def effect(value, context, **params):
        method = getattr(context["action"], method_name)
        return _perform(method, value, params, args, kwargs)

    return effect


def view_call(method_name, *args, **kwargs):
    """
    Creates an effect that will drop the current effect value,
    call the view's method with specified name
    with the specified arguments and keywords.
    @param method_name: the name of method belonging to the view.
    @type method_name: str
    """

    def effect(_value, context, **_params):
        method = getattr(context["view"], method_name)
        return _call(method, args, kwargs)

    return effect


def view_filter(method_name, *args, **kwargs):
    """
    Creates an effect that will call the view's method with the current
    value and specified arguments and keywords.
    @param method_name: the name of method belonging to the view.
    @type method_name: str
    """

    def effect(value, context, **_params):
        method = getattr(context["view"], method_name)
        return _filter(method, value, args, kwargs)

    return effect


def view_perform(method_name, *args, **kwargs):
    """
    Creates an effect that will call the view's method with the current
    value and specified arguments and the union of effect parameters and
    specified keywords (action's parameters take precedence).
    @param method_name: the name of method belonging to the view reference.
    @type method_name: str
    """

    def effect(value, context, **params):
        method = getattr(context["view"], method_name)
        return _perform(method, value, params, args, kwargs)

    return effect


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

    argspec = inspect.getargspec(method)

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
