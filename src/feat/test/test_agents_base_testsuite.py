# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.internet import defer
from twisted.trial.unittest import FailTest

from feat.test import common
from feat.agents.base import resource, testsuite, agent, replay
from feat.common import guard, fiber


@agent.register('descriptor')
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
        f.add_callback(fiber.drop_result, self.call_side_effect, 5)
        f.add_callback(state.medium.join_shard, shard='a')
        return f.succeed()

    @replay.immutable
    def some_immutable(self, state):
        t = state.medium.get_time()
        f = fiber.Fiber()
        f.add_callback(self.define_in_state, t)
        return f.succeed('var')


class TestHamsterball(testsuite.TestCase):

    def setUp(self):
        testsuite.TestCase.setUp(self)
        instance = self.ball.generate_agent(DummyAgent)
        instance.state.resources = self.ball.generate_resources(instance)
        self.instance = instance

    def testConstructDummyAgent(self):
        agent = self.ball.load(self.instance)
        self.assertIsInstance(agent, DummyAgent)
        self.assertTrue(self.ball.medium is not None)
        state = agent._get_state()
        self.assertIsInstance(state, guard.MutableState)
        self.assertIsInstance(state.resources, resource.Resources)

    def testMakeAllocation(self):
        agent = self.ball.load(self.instance)
        expectations = [testsuite.side_effect(resource.Allocation.initiate)]
        output, state = self.ball.call(expectations, agent.do_an_allocation)
        self.assertEqual(1, state.resources.allocated()['glass'])

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
        self.assertRaises(FailTest, self.ball.call, expectations,
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
