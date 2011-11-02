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

from feat.common.text_helper import format_block
from feat.test import common
from feat.simulation import driver
from feat.agents.base import descriptor


class TestDriver(common.TestCase):

    timeout = 2

    def setUp(self):
        self.driver = driver.Driver()
        return self.driver.initiate()

    @defer.inlineCallbacks
    def testSpawnAgency(self):
        test = 'agency = spawn_agency(start_host=False)\n'
        d = self.cb_after(None, self.driver._parser, 'on_finish')
        self.driver.process(test)
        yield d

        self.assertEqual(1, len(self.driver._agencies))
        self.assertEqual(self.driver._agencies[0],
                         self._get_local_var('agency'))

    @defer.inlineCallbacks
    def testCreateDescriptor(self):
        test = "desc = descriptor_factory('descriptor')\n"
        d = self.cb_after(None, self.driver._parser, 'on_finish')
        self.driver.process(test)
        yield d

        desc = self._get_local_var('desc')
        self.assertTrue(isinstance(desc, descriptor.Descriptor))
        self.log(desc.doc_id)
        fetched = yield self.driver._database_connection.get_document(
            desc.doc_id)
        self.assertEqual(desc.doc_id, fetched.doc_id)

    @defer.inlineCallbacks
    def testStartAgent(self):
        test = format_block("""
        agency = spawn_agency(start_host=False)
        agency.disable_protocol('setup-monitoring', 'Task')
        agency.start_agent(descriptor_factory('descriptor'))
        """)
        d = self.cb_after(None, self.driver._parser, 'on_finish')
        self.driver.process(test)
        yield d

        ag = self.driver._agencies[0]
        self.assertEqual(1, len(ag._agents))
        agent = ag._agents[0]
        self.assertIsInstance(agent.agent, common.DummyAgent)
        self.assertCalled(agent.agent, 'initiate', times=1)

    def testBreakpoints(self):

        def asserts1(_):
            self.assertTrue(self._get_local_var('desc1') is not None)
            self.assertFalse(self._local_var_exists('desc2'))

        def asserts2(_):
            self.assertTrue(self._get_local_var('desc2') is not None)

        test = format_block("""
        desc1 = descriptor_factory('descriptor')
        breakpoint('break')
        desc2 = descriptor_factory('descriptor')
        """)

        d1 = self.driver.register_breakpoint('break')
        d1.addCallback(asserts1)
        d2 = self.cb_after(None, self.driver._parser, 'on_finish')
        d2.addCallback(asserts2)

        self.driver.process(test)

        return defer.DeferredList([d1, d2])

    def _get_local_var(self, name):
        return self.driver._parser.get_local(name)

    def _local_var_exists(self, name):
        return name in self.driver._parser._locals
