# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from feat.agents import replay

from feat.interface.serialization import *

from . import common


class Base(replay.Replayable):

    def __init__(self, parent, value):
        replay.Replayable.__init__(self, parent, value)

    def init_state(self, state):
        pass

    @replay.mutable
    def double(self, state, value, minus=None):
        pass

    @replay.immutable
    def get_value(self, state):
        return state.value


class TestCombined(common.TestCase):

    def testBasic(self):
        pass
