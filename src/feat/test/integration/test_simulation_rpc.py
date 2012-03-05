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
from twisted.python import failure

from feat.test.integration import common

from feat.agents.base import agent, descriptor, replay
from feat.agents.common import rpc
from feat.common.text_helper import format_block
from feat.agents.application import feat

from feat.interface.recipient import *


@feat.register_descriptor("rpc_test_agent")
class Descriptor(descriptor.Descriptor):
    pass


@feat.register_agent("rpc_test_agent")
class Agent(agent.BaseAgent):

    @replay.mutable
    def initiate(self, state):
        state.value = None

    @replay.immutable
    def get_value(self, state):
        return state.value

    @rpc.publish
    @replay.mutable
    def set_value(self, state, value):
        result, state.value = state.value, value
        return result

    @rpc.publish
    def raise_error(self, Klass):
        raise Klass()

    @rpc.publish
    def return_failure(self, Klass):
        try:
            raise Klass()
        except:
            return failure.Failure()

    def not_published(self):
        pass


@common.attr(timescale=0.05)
class RPCTest(common.SimulationTest):

    def prolog(self):
        setup = format_block("""
        agency = spawn_agency(start_host=False)
        desc1 = descriptor_factory('rpc_test_agent')
        desc2 = descriptor_factory('rpc_test_agent')
        m1 = agency.start_agent(desc1)
        m2 = agency.start_agent(desc2)
        agent1 = m1.get_agent()
        agent2 = m2.get_agent()
        """)
        return self.process(setup)

    def testValidateProlog(self):
        agents = [x for x in self.driver.iter_agents()]
        self.assertEqual(2, len(agents))

    @defer.inlineCallbacks
    def testCallRemote(self):
        agent1 = self.get_local('agent1')
        agent2 = self.get_local('agent2')
        recip1 = IRecipient(agent1)
        recip2 = IRecipient(agent2)

        self.assertEqual(agent1.get_value(), None)
        self.assertEqual(agent2.get_value(), None)

        result = yield agent1.call_remote(recip2, "set_value", "spam")

        self.assertEqual(result, None)
        self.assertEqual(agent1.get_value(), None)
        self.assertEqual(agent2.get_value(), "spam")

        result = yield agent1.call_remote(recip2, "set_value", "bacon")

        self.assertEqual(result, "spam")
        self.assertEqual(agent1.get_value(), None)
        self.assertEqual(agent2.get_value(), "bacon")

        result = yield agent2.call_remote(recip1, "set_value", "eggs")

        self.assertEqual(result, None)
        self.assertEqual(agent1.get_value(), "eggs")
        self.assertEqual(agent2.get_value(), "bacon")

        result = yield agent2.call_remote(recip1, "set_value", "beans")

        self.assertEqual(result, "eggs")
        self.assertEqual(agent1.get_value(), "beans")
        self.assertEqual(agent2.get_value(), "bacon")

        # Calling on itself

        result = yield agent2.call_remote(recip2, "set_value", "ham")

        self.assertEqual(result, "bacon")
        self.assertEqual(agent1.get_value(), "beans")
        self.assertEqual(agent2.get_value(), "ham")

        result = yield agent1.call_remote(recip1, "set_value", "tomatoes")

        self.assertEqual(result, "beans")
        self.assertEqual(agent1.get_value(), "tomatoes")
        self.assertEqual(agent2.get_value(), "ham")

    def testRemoteError(self):
        agent1 = self.get_local('agent1')
        agent2 = self.get_local('agent2')
        recip1 = IRecipient(agent1)
        recip2 = IRecipient(agent2)

        self.assertEqual(agent1.get_value(), None)
        self.assertEqual(agent2.get_value(), None)

        d = defer.succeed(None)

        d = self.assertAsyncFailure(d, (ValueError, ), agent1.call_remote,
                                    recip2, "raise_error", ValueError)

        d = self.assertAsyncFailure(d, (TypeError, ), agent1.call_remote,
                                    recip2, "return_failure", TypeError)

        d = self.assertAsyncFailure(d, (ValueError, ), agent2.call_remote,
                                    recip1, "raise_error", ValueError)

        d = self.assertAsyncFailure(d, (TypeError, ), agent2.call_remote,
                                    recip1, "return_failure", TypeError)

        d = self.assertAsyncFailure(d, (ValueError, ), agent1.call_remote,
                                    recip1, "raise_error", ValueError)

        d = self.assertAsyncFailure(d, (TypeError, ), agent1.call_remote,
                                    recip1, "return_failure", TypeError)

        return d

    def testNotPublished(self):
        agent1 = self.get_local('agent1')
        agent2 = self.get_local('agent2')
        recip1 = IRecipient(agent1)
        recip2 = IRecipient(agent2)

        self.assertEqual(agent1.get_value(), None)
        self.assertEqual(agent2.get_value(), None)

        d = defer.succeed(None)

        d = self.assertAsyncFailure(d, (rpc.NotPublishedError, ),
                                    agent1.call_remote, recip2,
                                    "not_published")

        d = self.assertAsyncFailure(d, (rpc.NotPublishedError, ),
                                    agent2.call_remote, recip1,
                                    "not_published")

        d = self.assertAsyncFailure(d, (rpc.NotPublishedError, ),
                                    agent1.call_remote, recip1,
                                    "not_published")

        return d
