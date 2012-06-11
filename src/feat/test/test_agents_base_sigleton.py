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
from feat.common import defer
from feat.test import common, dummies
from feat.agents.base import singleton, task, agent


class DummyAgent(agent.BaseAgent, singleton.AgentMixin):

    def init_state(self, state, medium):
        state.medium = medium


class TestTask(task.BaseTask):

    protocol_id = 'test-task'


class TestSingleton(common.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        self.medium = dummies.DummyMedium(self)
        self.agent = DummyAgent(self.medium)
        self.medium.agent = self.agent
        yield singleton.AgentMixin.initiate(self.agent)

    @defer.inlineCallbacks
    def testRunningTask(self):
        yield self.agent.singleton_task(TestTask)
        self.assertEqual(1, len(self.medium.protocols))

        # second task doesn't start right away
        yield self.agent.singleton_task(TestTask)
        self.assertEqual(1, len(self.medium.protocols))

        # first task finishes
        self.medium.protocols[-1].deferred.callback(None)

        # second task will eventually run
        yield self.wait_for(
            self._protocols, timeout=2, kwargs=dict(exp=2), freq=0.01)

        # start another one
        yield self.agent.singleton_task(TestTask)
        self.assertEqual(2, len(self.medium.protocols))

        # now the current task will fail
        self.medium.protocols[-1].deferred.errback(TestException('aaa'))

        # third task will still run
        yield self.wait_for(
            self._protocols, timeout=2, kwargs=dict(exp=3), freq=0.01)

        # cleanup reactor after failing task
        self.flushLoggedErrors(TestException)

        # now finish the task
        self.medium.protocols[-1].deferred.callback(None)

        # start another one
        yield self.agent.singleton_task(TestTask)
        # assert it start right away
        self.assertEqual(4, len(self.medium.protocols))
        self.medium.protocols[-1].deferred.callback(None)

    def _protocols(self, exp):
        return len(self.medium.protocols) == exp


class TestException(Exception):
    pass
