# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from pprint import pformat

from feat.common import decorator, serialization

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


@serialization.register
class MutableState(serialization.Serializable):
    '''Object representing a mutable state.'''

    def __repr__(self):
        return "<MutableState: %s>" % pformat(self.__dict__)

    def __eq__(self, other):
        """
        Comparison of two states is used during replay to say whether we
        obtained the same result. Reference to 'medium' needs to be handled
        in special way, because during replay we use special dummy
        implementations.
        """
        if type(self) != type(other):
            return NotImplemented
        ignored_keys = ['medium', 'agent']
        for key in self.__dict__:
            if key in ignored_keys:
                continue
            if key not in other.__dict__:
                return False
            if not self.__dict__[key] == other.__dict__[key]:
                return False
        return True

    def __ne__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return not self.__eq__(other)


class Guarded(serialization.Serializable):

    def __init__(self, *args, **kwargs):
        state = MutableState()
        setattr(self, STATE_TAG, state)
        self.init_state(state, *args, **kwargs)

    def init_state(self, state, *args, **kwargs):
        '''
        Override to initialize the state. The extra arguments
        and keywords are the one passed to the constructor.

        THIS METHOD SHOULD NOT BE DECORATED WITH @mutable
        '''

    def recover(self, snapshot):
        setattr(self, STATE_TAG, snapshot)

    def snapshot(self):
        return self._get_state()

    ### Private Methods ###

    def _get_state(self):
        return getattr(self, STATE_TAG, None)

    def __eq__(self, other):
        if type(other) != type(self):
            return NotImplemented
        return self._get_state() == other._get_state()

    def __ne__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return not self.__eq__(other)
