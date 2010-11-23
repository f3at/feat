# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from zope.interface import implements

from feat.interface.serialization import *

from . import decorator, annotate, serialization

STATE_TAG = "_GUARDED_STATE_"


@decorator.simple_function
def mutable(function):

    def wrapper(self, *args, **kwargs):
        state = self._get_state()
        return function(self, state, *args, **kwargs)

    return wrapper


class MutableState(serialization.Serializable):
    '''Object representing a mutable state.'''


class Guarded(serialization.Serializable):

    def __init__(self):
        state = MutableState()
        setattr(self, STATE_TAG, state)
        self.init_state(state)

    def init_state(self, state):
        '''Override to initialize the state.'''

    def recover(self, snapshot, context={}):
        setattr(self, STATE_TAG, snapshot)

    def snapshot(self, context={}):
        return self._get_state()

    ### Private Methods ###

    def _get_state(self):
        return getattr(self, STATE_TAG, None)
