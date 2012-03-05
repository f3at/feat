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

from feat.common import serialization
from feat.test.integration import common
from feat.common.text_helper import format_block
from feat.agents.base import agent, replay, descriptor
from feat.common import fiber
from feat.agents.application import feat

from feat.interface.generic import *
from feat.interface.recipient import *


class U2(object):
    pass


@feat.register_descriptor('sample_agent')
class Descriptor(descriptor.Descriptor):
    pass


@feat.register_agent('sample_agent')
class SampleAgent(agent.BaseAgent):

    @replay.mutable
    def initiate(self, state):
        agent.BaseAgent.initiate(self)

    @replay.mutable
    def crazy(self, state, arg):
        return arg
        #return fiber.fail(U2())


msg = "Replayability is skipped because there is no way that replay "\
      "will pass when passing an unserializable object."


@common.attr(timescale=0.1, skip_replayability=msg)
class UnserializableTest(common.SimulationTest):

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        agency = spawn_agency(start_host=False)

        d = descriptor_factory('sample_agent')
        m = agency.start_agent(d)
        a = m.get_agent()
        """)

        yield self.process(setup)
        yield self.wait_for_idle(10)

    @defer.inlineCallbacks
    def testReturnUnserializableObject(self):
        a = self.get_local("a")
        d = a.crazy(U2())
        self.assertFailure(d, TypeError)
        yield d
