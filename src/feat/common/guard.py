# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import types

from zope.interface import implements

from feat.interface.serialization import *

from . import decorator, annotate, serialization

STATE_TAG = "_GUARDED_STATE_"


def freeze(value):
    '''Not Yet Implemented'''
    return value


@decorator.simple_function
def mutable(function):
    '''Add the instance internal state as the second parameter
    of the decorated function.'''

    def wrapper(self, *args, **kwargs):
        state = self._get_state()
        return function(self, state, *args, **kwargs)

    return wrapper


@decorator.simple_function
def immutable(function):
    '''Add the instance internal state as the second parameter
    of the decorated function.'''

    def wrapper(self, *args, **kwargs):
        state = freeze(self._get_state())
        return function(self, state, *args, **kwargs)

    return wrapper


class MutableState(serialization.Serializable):
    '''Object representing a mutable state.'''


class Guarded(serialization.Serializable):

    def __init__(self, *args, **kwargs):
        state = MutableState()
        setattr(self, STATE_TAG, state)
        self.init_state(state, *args, **kwargs)

    def init_state(self, state, *args, **kwargs):
        '''Override to initialize the state. The extra arguments
        and keywords are the one passed to the constructor.'''

    def recover(self, snapshot):
        setattr(self, STATE_TAG, snapshot)

    def snapshot(self):
        return self._get_state()

    ### Private Methods ###

    def _get_state(self):
        return getattr(self, STATE_TAG, None)
