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
# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from zope.interface import implements

from feat.agents.base import replay
from feat.common import journal, fiber
from feat.common.serialization import pytree

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
                  ISnapshotable(input).snapshot(),
                  ISnapshotable(side_effects).snapshot(),
                  ISnapshotable(output).snapshot())
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
        f1.add_callback(common.break_chain)
        f1.add_callback(self.async_add_double)
        f1.succeed(value1)

        f2 = fiber.Fiber()
        f2.add_callback(common.break_chain)
        f2.add_callback(self.async_add_double)
        f2.succeed(value2)

        def sum_values(result):
            return sum([value for success, value in result if success])

        f = fiber.FiberList([f1, f2])
        f.succeed()
        f.add_callback(sum_values)

        return f

    @replay.mutable
    def async_add_double(self, state, value, minus=None):
        result = value * 2 - (minus if minus is not None else 0)
        state.sum += result
        return fiber.Fiber().add_callback(common.break_chain).succeed(result)

    @replay.immutable
    def get_sum(self, state):
        return state.sum

    @replay.entry_point
    def reentrance_sync_error(self, state):
        return self.sync_main(1, 2)

    @replay.mutable
    def reentrance_async_error1(self, state):
        f = fiber.Fiber()
        f.add_callback(self.sync_main, 2)
        f.succeed(1)
        return f

    @replay.mutable
    def reentrance_async_error2(self, state):
        f = fiber.Fiber()
        f.add_callback(common.break_chain)
        f.add_callback(self.sync_main, 2)
        f.succeed(1)
        return f


class DymmyReplayable(replay.Replayable):

    def init_state(self, state, parent, first):
        state.sum = first

    @replay.entry_point
    def test(self, state, value):
        # Inside the ball
        state.sum += value
        f = fiber.succeed(value + 1)
        f.add_callback(self._step2)
        return f

    def _step2(self, value):
        # Outside the ball
        self._step3(value + 1)
        # Two times to be sure each calls are recorded
        self._step4(value + 2)

    @replay.mutable
    def _step3(self, state, value):
        # Inside the ball
        state.sum += value

    @replay.mutable
    def _step4(self, state, value):
        # Inside the ball
        state.sum += value


class TestCombined(common.TestCase):

    def setUp(self):
        self.serializer = pytree.Serializer()
        self.unserializer = pytree.Unserializer()
        self.keeper = journal.StupidJournalKeeper(self.serializer,
                                                  self.unserializer)

    def testInOut(self):
        root = journal.RecorderRoot(self.keeper)
        obj = DymmyReplayable(root, 0)
        return obj.test(10)

    def testReentranceError(self):
        root = journal.RecorderRoot(self.keeper)
        obj = Base(root, 18)

        d = self.assertAsyncFailure(None, ReentrantCallError,
                                    obj.reentrance_sync_error)

#        d = self.assertAsyncFailure(d, [ReentrantCallError],
#                                    obj.reentrance_async_error1)
#
#        d = self.assertAsyncFailure(d, [ReentrantCallError],
#                                    obj.reentrance_async_error2)

        return d

    def testSynchronousCalls(self):
        root = journal.RecorderRoot(self.keeper)

        base = Base(root, 18)

        d = self.assertAsyncEqual(None, 18, base.get_sum)
        d = self.assertAsyncEqual(d, 24, base.sync_main, 5, 7)
        d = self.assertAsyncEqual(d, 42, base.get_sum)
        d = self.assertAsyncEqual(d, 24, base.sync_add_double, 13, minus=2)
        d = self.assertAsyncEqual(d, 66, base.get_sum)

        return d

    def testAsynchronousCalls(self):
        root = journal.RecorderRoot(self.keeper)

        base = Base(root, 18)

        d = self.assertAsyncEqual(None, 18, base.get_sum)
        d = self.assertAsyncEqual(d, 24, base.async_main, 5, 7)
        d = self.assertAsyncEqual(d, 42, base.get_sum)
        d = self.assertAsyncEqual(d, 24, base.async_add_double, 13, minus=2)
        d = self.assertAsyncEqual(d, 66, base.get_sum)

        return d
