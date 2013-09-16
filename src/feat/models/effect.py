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
This module defines a set of generic effect factories.
See the individual function docstrings for an explanation of each effect
factory.

EFFECT DEFINITION:

Effects are standardized callables with known parameters that can perform
different actions.

An effect takes two arguments and keyword arguments:

  1. the current value in a processing chain.

  2. current context: a dictionary, containing the following keys when
     meaningful:

      - model:  the current model
      - view:   the current view
      - action: the current action
      - key:    the current key

  3. An effect's keywords arguments are extra dynamic parameters
     that could be used by the effect, usually action parameters.

The effect's result is ALWAYS a defer.Deferred() instance fired
with the new value of the processing chain.

FIXME: this last sentence seems wrong.  I see effects that return values as is,
without wrapping them in a Deferred.
"""

from feat.common import defer, time
from feat.models import reference


def delay(effect, result=None, delay=0.001):
    """
    Returns a new effect that will delay the execution
    of the given effect and return the specified result right away.

    @param effect: the effect to delay
    @type  effect: callable
    @param result: the value to return right away
    @type  result: Any
    @param delay:  the time to wait before performing
                   the specified effect, in seconds
    @type  delay:  float

    @return: a new effect that will delay the given effect
    @rtype:  callable
    """

    def delay(value, context, **params):
        d = defer.Deferred()
        d.addCallback(effect, context, **params)
        time.call_next(d.callback, value)
        return result

    return delay


def select_param(param_name, default=None):
    """
    Returns an effect that drops the current value and returns the parameter
    with the specified name instead, or the specified default value if the
    parameter is not specified.
    """

    def select_param(_value, _context, **params):
        return params.pop(param_name, default)

    return select_param


def local_ref(*parts):
    """
    Returns an effect that returns a local reference constructed from the
    given factory arguments joined with the context's 'key'.

    This is a reference builder with a specified base location:
    Using getter.local_ref("some", "base") to get a value with context key
    "toto" will give reference.Local("some", "base", "toto")
    """

    def local_ref(_value, context, **_params):
        return reference.Local(*(parts + (context["key"], )))

    return local_ref


def relative_ref(*parts):
    """
    Create a reference builder with specified relative location.
    using getter.relative_ref("some", "submodel") to get a value with key
    "toto" will gives reference.Relative("some", "submodel", "toto")
    """

    def relative_ref(_value, context, **_params):
        return reference.Relative(*(parts + (context["key"], )))

    return relative_ref


def context_value(name):
    """
    Returns an effect that drops the current value, and replaces it with
    the value from the context with the given name.
    """

    def context_value(_value, context, **_params):
        return defer.succeed(context[name])

    return context_value


def static_value(value):
    '''Return an effect giving always the same value.'''

    def static_value(_value, _context):
        return defer.succeed(value)

    return static_value


def identity(value, context, *args, **kwargs):
    return value


def subroutine(*effects):
    """
    Returns an effect performing a list of effects. The value passed to each
    effect is a result of the previous effect.
    """

    def subroutine(value, context, *args, **kwargs):
        d = defer.succeed(value)
        for effect in effects:
            d.addCallback(effect, context, *args, **kwargs)
        return d

    return subroutine


def store_in_context(key):

    def store_in_context(value, context, *args, **kwargs):
        context[key] = value
        return defer.succeed(value)

    return store_in_context
