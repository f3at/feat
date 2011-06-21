from twisted.python import failure

from feat.test.integration import common

from feat.agencies.common import StateMachineMixin
from feat.agents.base import agent, descriptor, replay
from feat.common import serialization, defer, fiber
from feat.common.text_helper import format_block


@descriptor.register("replay_test_agent")
class Descriptor(descriptor.Descriptor):
    pass


@agent.register("replay_test_agent")
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
        agency = spawn_agency()
        agency.disable_protocol('setup-monitoring', 'Task')
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
