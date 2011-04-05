from twisted.internet import defer

from feat.common import fiber
from feat.common.text_helper import format_block
from feat.test.integration import common
from feat.agents.base import (agent, descriptor, partners,
                              task, replay, document, )


class Task(task.BaseTask):

    def __init__(self, *args, **kwargs):
        task.BaseTask.__init__(self, *args, **kwargs)

    @replay.mutable
    def initiate(self, state):
        pass


@document.register
class Descriptor(descriptor.Descriptor):

    document_type = 'task-agent'


@agent.register('task-agent')
class Agent(agent.BaseAgent):

    @replay.mutable
    def initiate(self, state):
        agent.BaseAgent.initiate(self)
        f = fiber.succeed()
        f.add_callback(fiber.drop_result, state.medium.initiate_task, Task)
        f.add_callback(Task.notify_finish)
        return f


class TaskAgentTest(common.SimulationTest):

    skip = 'See bug https://www.pivotaltracker.com/story/show/11878609'

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        agency = spawn_agency()
        agent = agency.start_agent(descriptor_factory('task-agent'))
        """)
        yield self.process(setup)

    def testTask(self):
        pass
