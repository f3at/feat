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
from feat.test.integration import common
from feat.agents.base import agent, descriptor, notifier, replay
from feat.common import defer, text_helper, time
from feat.agents.application import feat


@feat.register_descriptor('notifier-agent')
class Descriptor(descriptor.Descriptor):
    pass


@feat.register_agent('notifier-agent')
class Agent(agent.BaseAgent, notifier.AgentMixin):
    pass


@common.attr(timescale=0.05)
class TestNotifier(common.SimulationTest):

    timeout = 3

    @defer.inlineCallbacks
    def prolog(self):
        setup = text_helper.format_block("""
        agency = spawn_agency()
        agency.start_agent(descriptor_factory('notifier-agent'), \
                           run_startup=False)
        """)
        yield self.process(setup)
        self.agent = self.get_local('_').get_agent()

    @defer.inlineCallbacks
    def testWaitCallbackAndErrback(self):
        # test callback
        d = self.agent.wait_for_event('event')
        self.assertIsInstance(d, defer.Deferred)
        self.agent.callback_event('event', 'result')
        result = yield d
        self.assertEqual('result', result)

        # test errback
        d = self.agent.wait_for_event('event2')
        self.agent.errback_event('event2', RuntimeError('failure'))
        self.assertFailure(d, RuntimeError)
        yield d

    @defer.inlineCallbacks
    def testTimeouts(self):
        d = self.agent.wait_for_event('event', timeout=0.05)
        d2 = self.agent.wait_for_event('event', timeout=2)
        self.assertFailure(d, notifier.TimeoutError)
        yield d

        # this should be safe
        self.agent.callback_event('event', 'result')
        res = yield d2
        self.assertEqual(res, 'result')
