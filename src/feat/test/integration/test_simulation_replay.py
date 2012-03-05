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
from twisted.python import failure

from feat.test.integration import common

from feat.agencies.common import StateMachineMixin
from feat.agents.base import agent, descriptor, replay
from feat.common import serialization, defer, fiber
from feat.common.text_helper import format_block
from feat.agents.application import feat


@feat.register_descriptor("replay_test_agent")
class Descriptor(descriptor.Descriptor):
    pass


@feat.register_agent("replay_test_agent")
class Agent(agent.BaseAgent):

    @replay.mutable
    def initiate(self, state):
        state.calls = 0

    @replay.entry_point
    def test_side_effect(self, state, value):
        state.calls += 1
        dummy = self.creat_dummy(value + 1)
        f = fiber.Fiber()
        f.add_callback(fiber.drop_param, dummy.wait_for_state, "done")
        f.add_callback(getattr, "value")
        return f.succeed()

    @replay.side_effect
    def creat_dummy(self, value):
        return Dummy(self.do_stuff, value + 2)

    @replay.entry_point
    def do_stuff(self, state, value):
        state.calls += 1
        return value + 3


@serialization.register
class Dummy(serialization.Serializable, StateMachineMixin):

    def __init__(self, call, *args):
        StateMachineMixin.__init__(self, "waiting")
        self.value = None
        d = call(*args)
        d.addCallback(self._store)

    def _store(self, v):
        self.value = v
        self._set_state("done")


@common.attr(timescale=0.05)
class ReplayTest(common.SimulationTest):

    def prolog(self):
        setup = format_block("""
        agency = spawn_agency(start_host=False)
        desc = descriptor_factory('replay_test_agent')
        medium = agency.start_agent(desc)
        agent = medium.get_agent()
        """)
        return self.process(setup)

    def testValidateProlog(self):
        agents = [x for x in self.driver.iter_agents()]
        self.assertEqual(1, len(agents))

    @defer.inlineCallbacks
    def testSideEffectReset(self):
        agent = self.get_local('agent')
        result = yield agent.test_side_effect(42)
        self.assertEqual(result, 42 + 1 + 2 +3)
