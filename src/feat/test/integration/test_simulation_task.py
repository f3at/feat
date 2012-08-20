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
from twisted.internet import defer

from feat.common import fiber
from feat.common.text_helper import format_block
from feat.test.integration import common
from feat.agents.base import (agent, descriptor, partners,
                              task, replay, notifier, )
from feat.database import document
from feat.agents.application import feat


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


class WaitingTask(task.BaseTask):

    @replay.entry_point
    def initiate(self, state):
        return state.agent.wait_for_event('finish_task')


@feat.register_descriptor('task-agent')
class Descriptor(descriptor.Descriptor):
    pass


@feat.register_agent('task-agent')
class Agent(agent.BaseAgent, notifier.AgentMixin):

    @replay.mutable
    def run_tasks(self, state):
        state.task_result1 = None
        state.task_result2 = None

        t = state.medium.initiate_protocol(Task, 18)
        f = fiber.succeed(t)
        f.add_callback(Task.notify_finish)
        f.add_callback(self.set_result, "task_result1")
        f.add_callback(fiber.drop_param,
                       state.medium.initiate_protocol, Task, 42)
        f.add_callback(Task.notify_finish)
        f.add_callback(self.set_result, "task_result2")
        return f

    @replay.immutable
    def start_task(self, state, value):
        return state.medium.initiate_protocol(Task, value)

    @replay.journaled
    def run_observed_task(self, state):
        task = state.medium.initiate_protocol(WaitingTask)
        state.observer = state.medium.observe(task.notify_finish)
        return state.observer

    @replay.journaled
    def trigger_finish(self, state, value):
        self.callback_event('finish_task', value)

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

    @defer.inlineCallbacks
    def testTask(self):
        agent = self.get_local('agent')
        yield agent.run_tasks()
        self.assertEqual(agent.get_result("task_result1"), 18 + 18*2)
        self.assertEqual(agent.get_result("task_result2"), 42 + 42*2)
        task = yield agent.start_task(66)
        result = yield task.notify_finish()
        self.assertEqual(result, 66 + 66*2)

    @defer.inlineCallbacks
    def testObservingTask(self):
        agent = self.get_local('agent')
        observer = yield agent.run_observed_task()
        self.info('Checking if the task is active')
        self.assertTrue(observer.active())
        yield agent.trigger_finish('result')
        fib = observer.notify_finish()
        res = yield fib.start()
        self.assertEqual('result', res)

        self.assertFalse(observer.active())
        self.assertEqual('result', observer.get_result())
