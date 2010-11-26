# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from zope.interface import implements

from feat.agents import replay
from feat.common import journal, fiber

from feat.interface.serialization import *
from feat.interface.journal import *

from . import common


class DummyJournalKeeper(object):

    implements(IJournalKeeper)

    def __init__(self):
        self.records = []
        self.registry = {}

    ### IJournalKeeper Methods ###

    def register(self, recorder):
        self.registry[recorder.journal_id] = recorder

    def record(self, instance_id, entry_id,
               fiber_id, fiber_depth, input, side_effects, output):
        record = (instance_id, entry_id, fiber_id, fiber_depth,
                  ISnapshot(input).snapshot(),
                  ISnapshot(side_effects).snapshot(),
                  ISnapshot(output).snapshot())
        self.records.append(record)


class Base(replay.Replayable):

    def __init__(self, parent, start_value):
        replay.Replayable.__init__(self, parent, start_value)

    def init_state(self, state, parent, start_value):
        state.sum = start_value

    @replay.entry_point
    def sync_main(self, state, value1, value2):
        return self.sync_add_double(value1) + self.sync_add_double(value2)

    @replay.mutable
    def sync_add_double(self, state, value, minus=None):
        result = value * 2 - (minus if minus is not None else 0)
        state.sum += result
        return result

    @replay.entry_point
    def async_main(self, state, value1, value2):
        f1 = fiber.Fiber()
        f1.addCallback(self.async_add_double)
        f1.succeed(value1)

        f2 = fiber.Fiber()
        f2.addCallback(self.async_add_double)
        f2.succeed(value2)

        def sum_values(result):
            return sum([value for success, value in result if success])

        f = fiber.FiberList([f1, f2])
        f.addCallback(sum_values)

        return f

    @replay.mutable
    def async_add_double(self, state, value, minus=None):
        result = value * 2 - (minus if minus is not None else 0)
        state.sum += result
        return result

    @replay.immutable
    def get_sum(self, state):
        return state.sum

    @replay.entry_point
    def reentrance_error1(self, state):
        return self.sync_main(1, 2)

    @replay.mutable
    def reentrance_error2(self, state):
        return self.sync_main(1, 2)


class TestCombined(common.TestCase):

    def testSynchronousCalls(self):
        keeper = journal.InMemoryJournalKeeper()
        root = journal.RecorderRoot(keeper)

        base = Base(root, 18)

        d = self.assertAsyncEqual(None, 18, base.get_sum)
        d = self.assertAsyncEqual(d, 24, base.sync_main, 5, 7)
        d = self.assertAsyncEqual(d, 42, base.get_sum)
        d = self.assertAsyncEqual(d, 24, base.sync_add_double, 13, minus=2)
        d = self.assertAsyncEqual(d, 66, base.get_sum)

        return d
