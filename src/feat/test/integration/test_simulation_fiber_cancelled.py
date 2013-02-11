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

from feat.test import common as test_common
from feat.test.integration import common

from feat.agents.base import agent, descriptor, replay
from feat.agents.base import requester, replier, notifier
from feat.agencies import message
from feat.common import fiber
from feat.common.text_helper import format_block
from feat.interface import protocols
from feat.agents.application import feat

from feat.interface.recipient import *


@feat.register_descriptor("test_prop_agent")
class Descriptor(descriptor.Descriptor):
    pass


@feat.register_agent("test_prop_agent")
class Agent(agent.BaseAgent, notifier.AgentMixin,
        test_common.Mock):

    @replay.mutable
    def initiate(self, state):
        test_common.Mock.__init__(self)
        state.medium.register_interest(LateReplier)

    @test_common.Mock.stub
    def called():
        pass


class LateRequester(requester.BaseRequester):

    protocol_id = 'test_late'
    timeout = 1

    @replay.entry_point
    def initiate(self, state):
        msg = message.RequestMessage()
        state.medium.request(msg)


class LateReplier(replier.BaseReplier):

    protocol_id = 'test_late'

    @replay.entry_point
    def requested(self, state, request):
        f = self.fiber_new()
        f.add_callback(fiber.drop_param,\
                state.agent.wait_for_event, "late event")
        f.add_callback(self.done)
        return f.succeed()

    @replay.mutable
    def done(self, state, _):
        # the following call is only used to make an assertion
        state.agent.called()
        response = message.ResponseMessage()
        state.medium.reply(response)


@common.attr(timescale=1)
@common.attr('slow')
class ProtoFiberCancelTest(common.SimulationTest):

    timeout = 5

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        agency = spawn_agency(start_host=False)
        desc = descriptor_factory('test_prop_agent')
        medium = agency.start_agent(desc)
        agent = medium.get_agent()
        """)
        yield self.process(setup)

    def testValidateProlog(self):
        self.assertEqual(1, self.count_agents('test_prop_agent'))

    @defer.inlineCallbacks
    def testLateRequester(self):

        medium = self.get_local('medium')
        agent = self.get_local('agent')
        recip = IRecipient(agent)

        requester = agent.initiate_protocol(LateRequester, recip)

        d = requester.notify_finish()
        self.assertFailure(d, protocols.ProtocolFailed)
        yield d

        yield agent.callback_event("late event", None)

        self.assertCalled(agent, 'called', times=0)
