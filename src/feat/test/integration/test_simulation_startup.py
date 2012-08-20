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
from feat.common import first, defer
from feat.test.integration import common
from feat.common.text_helper import format_block
from feat.agents.base import descriptor, agent, replay
from feat.database import document

from feat.database.interface import ConflictError
from feat.agents.application import feat


@feat.register_agent('some-stupid-agent')
class SomeAgent(agent.BaseAgent):

    @replay.mutable
    def do_sth_in_desc(self, state):

        def do_changes(desc):
            desc.field = 'sth'
            return desc

        return self.update_descriptor(do_changes)


@feat.register_descriptor('some-stupid-agent')
class Descriptor(descriptor.Descriptor):

    document.field('field', None)


@common.attr(timescale=0.05)
class SimulateRunningAgentTwice(common.SimulationTest):

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        agency1 = spawn_agency()
        agency2 = spawn_agency()
        desc = descriptor_factory('some-stupid-agent')
        """)
        yield self.process(setup)
        self.agency1, self.agency2 = self.get_local('agency1', 'agency2')
        yield self.run_agent('agency1')

    def run_agent(self, agency):
        return self.process(format_block("""
        desc = reload_document(desc)
        %(agency)s.start_agent(desc)
        """) % {'agency': agency})

    def get_agent(self):
        self.assertEqual(1, self.count_agents('some-stupid-agent'))
        return first(self.driver.iter_agents('some-stupid-agent'))

    def get_agency(self):
        a = self.driver.find_agency(self.get_agent().get_descriptor().doc_id)
        return a

    @defer.inlineCallbacks
    def testStartingAgain(self):
        a = self.get_agency()
        self.assertEqual(a, self.agency1)
        self.info('Running agent second time')
        yield self.run_agent('agency2')
        yield self.wait_for_idle(5)
        a = self.get_agency()
        self.assertEqual(a, self.agency2)

        yield self.run_agent('agency1')
        yield self.wait_for_idle(5)
        a = self.get_agency()
        self.assertEqual(a, self.agency1)

    @defer.inlineCallbacks
    def testAgentGetsUpdateConflict(self):
        self.assertEqual(1, self.count_agents('some-stupid-agent'))

        # update descriptor remotely
        desc = self.get_local('desc')
        desc = yield self.driver.reload_document(desc)
        desc.instance_id += 1
        yield self.driver.save_document(desc)
        d = self.get_agent().get_agent().do_sth_in_desc()
        self.assertFailure(d, ConflictError)
        yield d
        yield self.wait_for_idle(3)
        self.assertEqual(0, self.count_agents('some-stupid-agent'))
