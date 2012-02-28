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
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.internet import defer
from twisted.trial.unittest import FailTest

from feat.test import common
from feat.agents.base import resource, testsuite, agent, replay, manager
from feat.agencies import message, recipient
from feat.common import guard, fiber
from feat.agencies.replay import AgencyManager

from feat.interface.journal import *
from feat.agents.application import feat


@feat.register_agent('descriptor')
class DummyAgent(common.DummyAgent):

    @replay.mutable
    def do_an_allocation(self, state):
        state.resources.define('glass', 10)
        state.resources.allocate(glass=1)

    @replay.mutable
    def define_in_state(self, state, name, value):
        setattr(state, name, value)

    @replay.mutable
    def call_side_effect(self, state, par=None):
        t = state.medium.get_time()
        state.time = t
        return t

    @replay.mutable
    def perform_async_job(self, state):
        f = fiber.Fiber()
        f.add_callback(fiber.drop_param, self.call_side_effect, 5)
        f.add_callback(state.medium.join_shard, shard='a')
        return f.succeed()

    @replay.immutable
    def some_immutable(self, state):
        t = state.medium.get_time()
        f = fiber.Fiber()
        f.add_callback(self.define_in_state, t)
        return f.succeed('var')


class DummyManager(manager.BaseManager):

    protocol_id = 'dummy-contract'

    @replay.immutable
    def initiate(self, state):
        msg = message.Announcement()
        msg.payload['level'] = 0
        msg.payload['joining_agent'] = state.agent.get_own_address()
        state.medium.announce(msg)


class TestHamsterball(testsuite.TestCase):

    def setUp(self):
        testsuite.TestCase.setUp(self)
        instance = self.ball.generate_agent(DummyAgent)
        instance.state.value = 5
        instance.state.resources = self.ball.generate_resources(instance)
        self.instance = instance

    def testConstructDummyAgent(self):
        agent = self.ball.load(self.instance)
        self.assertIsInstance(agent, DummyAgent)
        self.assertTrue(self.ball.medium is not None)
        state = agent._get_state()
        self.assertIsInstance(state, guard.MutableState)
        self.assertEqual(5, state.value)
        self.assertIsInstance(state.resources, resource.Resources)

    def testStateChangingFunc(self):
        agent = self.ball.load(self.instance)
        self.assertFalse('var' in agent._get_state().__dict__)
        output, state = self.ball.call(None, agent.define_in_state, 'var', 4)
        self.assertEqual(4, state.var)
        self.assertTrue('var' in agent._get_state().__dict__)

    def testCallingSideEffect(self):
        agent = self.ball.load(self.instance)
        expectations = [
            testsuite.side_effect('AgencyAgent.get_time', 'result')]
        output, state = self.ball.call(expectations, agent.call_side_effect)
        self.assertEqual('result', output)
        self.assertEqual('result', state.time)

    def testUnconsumedSideEffects(self):
        agent = self.ball.load(self.instance)
        expectations = [
            testsuite.side_effect('AgencyAgent.get_time', 'result'),
            testsuite.side_effect('AgencyAgent.get_time', 'result2')]
        self.assertRaises(ReplayError, self.ball.call, expectations,
                          agent.call_side_effect)

    def testAsyncStuff(self):
        agent = self.ball.load(self.instance)
        output, state = self.ball.call(None, agent.perform_async_job)
        self.assertFiberTriggered(output, fiber.TriggerType.succeed, None)
        self.assertFiberCalls(output, agent.call_side_effect, args=(5, ))
        self.assertFiberCalls(output, state.medium.join_shard,
                              kwargs=dict(shard='a'))
        self.assertRaises(FailTest, self.assertFiberCalls,
                          output, agent.call_side_effect, args=(1, ))

    def testWorksSameForImmutable(self):
        agent = self.ball.load(self.instance)
        output, state = self.ball.call(None, agent.perform_async_job)
        expectations = [
            testsuite.side_effect('AgencyAgent.get_time', 'result')]
        output, state = self.ball.call(expectations, agent.some_immutable)
        self.assertFalse('var' in state.__dict__)
        self.assertFiberTriggered(output, fiber.TriggerType.succeed, 'var')
        self.assertFiberCalls(output, agent.define_in_state, args=('result', ))

    def testContstructingManager(self):
        m = self.ball.generate_manager(self.instance, DummyManager)
        self.manager = self.ball.load(m)
        s = self.manager._get_state()
        self.assertIsInstance(s.agent, DummyAgent)
        self.assertIsInstance(s.medium, AgencyManager)

    def testManangerMethod(self):
        m = self.ball.generate_manager(self.instance, DummyManager)
        manager = self.ball.load(m)
        address = recipient.Agent(agent_id=self.ball.descriptor.doc_id,
                                  route=self.ball.descriptor.shard)
        args = (
            testsuite.message(payload=dict(level=0, joining_agent=address)), )
        expected = [
            testsuite.side_effect('AgencyAgent.get_own_address', address),
            testsuite.side_effect('AgencyManager.announce', args=args)]
        output, state = self.ball.call(expected, manager.initiate)
