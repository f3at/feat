from twisted.internet import defer

from feat.common import fiber
from feat.common.text_helper import format_block
from feat.test.integration import common
from feat.agents.base import (agent, descriptor, partners,
                              task, replay, document, )


class Task(task.BaseTask):

    def __init__(self, *args, **kwargs):
        task.BaseTask.__init__(self, *args, **kwargs)

    @replay.entry_point
    def initiate(self, state, value):
        state.value = 0
        f = fiber.Fiber()
        f.add_callback(self.do_stuff)
        f.add_callback(common.break_chain)
        f.add_callback(self.do_stuff)
        f.add_callback(self.finished)
        return f.succeed(value)

    @replay.mutable
    def do_stuff(self, state, param):
        state.value += param
        return param * 2

    @replay.immutable
    def finished(self, state, param):
        return state.value


@descriptor.register('task-agent')
class Descriptor(descriptor.Descriptor):
    pass


@agent.register('task-agent')
class Agent(agent.BaseAgent):

    @replay.entry_point
    def initiate(self, state):
        agent.BaseAgent.initiate(self)
        state.task_result1 = None
        state.task_result2 = None

        t = state.medium.initiate_task(Task, 18)
        f = fiber.succeed(t)
        f.add_callback(Task.notify_finish)
        f.add_callback(self.set_result, "task_result1")
        f.add_callback(fiber.drop_result, state.medium.initiate_task, Task, 42)
        f.add_callback(Task.notify_finish)
        f.add_callback(self.set_result, "task_result2")
        return f

    @replay.immutable
    def start_task(self, state, value):
        return state.medium.initiate_task(Task, value)

    @replay.mutable
    def set_result(self, state, result, attr):
        setattr(state, attr, result)
        return result

    @replay.immutable
    def get_result(self, state, attr):
        return getattr(state, attr)


@common.attr(timescale=0.05)
class TaskAgentTest(common.SimulationTest):

    def prolog(self):
        setup = format_block("""
        agency = spawn_agency()
        medium = agency.start_agent(descriptor_factory('task-agent'))
        agent = medium.get_agent()
        """)
        return self.process(setup)

    def testValidateProlog(self):
        agents = [x for x in self.driver.iter_agents()]
        self.assertEqual(1, len(agents))

    @defer.inlineCallbacks
    def testTask(self):
        agent = self.get_local('agent')
        self.assertEqual(agent.get_result("task_result1"), 18 + 18*2)
        self.assertEqual(agent.get_result("task_result2"), 42 + 42*2)
        task = yield agent.start_task(66)
        result = yield task.notify_finish()
        self.assertEqual(result, 66 + 66*2)
