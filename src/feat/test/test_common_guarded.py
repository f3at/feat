# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from feat.common import guarded

from . import common


class Dummy(guarded.Guarded):

    def init_state(self, state):
        state.value = 0

    @guarded.mutable
    def double(self, state, value, minus=None):
        result = value * 2
        if minus is not None:
            result -= minus
        state.value += result
        return result

    @guarded.mutable
    def get_value(self, state):
        return state.value


class TestIntrospection(common.TestCase):

    def testBasicGuarded(self):
        obj = Dummy()
        self.assertEqual(obj.get_value(), 0)
        self.assertEqual(obj.double(2), 4)
        self.assertEqual(obj.get_value(), 4)
        self.assertEqual(obj.double(3, minus=1), 5)
        self.assertEqual(obj.get_value(), 9)
