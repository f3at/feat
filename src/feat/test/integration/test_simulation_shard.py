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
from zope.interface import implements

from feat.agents.base import replay, descriptor, agent
from feat.agents.common import shard
from feat.common import defer, first, time
from feat.common.text_helper import format_block
from feat.agents.application import feat

from feat.interface.recipient import *

from feat.test.integration import common


@feat.register_descriptor("test_shard_notif_agent")
class Descriptor(descriptor.Descriptor):
    pass


@feat.register_agent("test_shard_notif_agent")
class Agent(agent.BaseAgent):

    implements(shard.IShardNotificationHandler)

    @replay.mutable
    def initiate(self, state):
        self.clear()
        shard.register_for_notifications(self)

    @replay.mutable
    def clear(self, state):
        state.new_shards = []
        state.old_shards = []

    @replay.immutable
    def get_new_shards(self, state):
        return list(state.new_shards)

    @replay.immutable
    def get_old_shards(self, state):
        return list(state.old_shards)

    ### IShardNotificationHandler Methods ###

    @replay.mutable
    def on_new_neighbour_shard(self, state, recipient):
        state.new_shards.append(recipient)

    @replay.mutable
    def on_neighbour_shard_gone(self, state, recipient):
        state.old_shards.append(recipient)


@common.attr(timescale=0.1)
class StructuralPartners(common.SimulationTest):

    timeout = 30

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        agency = spawn_agency()
        agency = spawn_agency()
        """)

        yield self.process(setup)
        yield self.wait_for_idle(20)
        self.raage_medium = first(self.driver.iter_agents('raage_agent'))
        self.shard_medium = first(self.driver.iter_agents('shard_agent'))

    def testValidateProlog(self):
        self.assertEqual(1, self.count_agents('shard_agent'))
        self.assertEqual(2, self.count_agents('host_agent'))
        self.assertEqual(1, self.count_agents('raage_agent'))

    @defer.inlineCallbacks
    def testRaageGetsRestarted(self):
        yield self.raage_medium._terminate()
        yield self.wait_for_idle(10)
        self.assertEqual(1, self.count_agents('raage_agent'))

    @common.attr(timeout=80)
    @defer.inlineCallbacks
    def testArmagedon(self):
        '''
        In this test we kill the host with Raage and Shard.
        Then we assert that they were recreated.
        '''
        d1 = self.raage_medium._terminate()
        d2 = self.shard_medium._terminate()
        d3 = first(self.driver.iter_agents('host_agent'))._terminate()
        yield defer.DeferredList([d1, d2, d3])

        yield self.wait_for_idle(30)
        self.assertEqual(1, self.count_agents('raage_agent'))
        self.assertEqual(1, self.count_agents('shard_agent'))
        self.assertEqual(1, self.count_agents('host_agent'))


@common.attr(timescale=0.2)
class TestShardNotification(common.SimulationTest):

    def prolog(self):
        pass

    @defer.inlineCallbacks
    def testNotifications(self):

        def check_no_changes(agent_medium):
            agent = agent_medium.get_agent()
            new_shards = agent.get_new_shards()
            old_shards = agent.get_old_shards()
            self.assertEqual(len(new_shards), 0)
            self.assertEqual(len(old_shards), 0)

        def check_new_shard(agent_medium, shard_medium):
            agent = agent_medium.get_agent()
            shard = shard_medium.get_agent()
            new_shards = agent.get_new_shards()
            old_shards = agent.get_old_shards()
            self.assertEqual(len(new_shards), 1)
            self.assertEqual(len(old_shards), 0)
            self.assertEqual(new_shards[0], IRecipient(shard))
            agent.clear()

        def check_shard_gone(agent_medium, *shard_mediums):
            agent = agent_medium.get_agent()
            shards = [IRecipient(m.get_agent()) for m in shard_mediums]
            new_shards = agent.get_new_shards()
            old_shards = agent.get_old_shards()
            self.assertEqual(len(new_shards), 0)
            self.assertEqual(len(old_shards), len(shards))
            self.assertEqual(set(old_shards), set(shards))
            agent.clear()

        drv = self.driver

        agency1 = yield drv.spawn_agency(start_host=False)
        sa1_desc = yield drv.descriptor_factory("shard_agent",
                                                shard=u"shard1")
        sa1 = yield agency1.start_agent(sa1_desc)

        yield self.wait_for_idle(10)

        na1_desc = yield drv.descriptor_factory("test_shard_notif_agent",
                                                shard=u"shard1")
        na1 = yield agency1.start_agent(na1_desc)

        yield self.wait_for_idle(10)

        agency2 = yield drv.spawn_agency(start_host=False)
        sa2_desc = yield drv.descriptor_factory("shard_agent",
                                                shard=u"shard2")
        sa2 = yield agency2.start_agent(sa2_desc)

        yield self.wait_for_idle(10)

        check_new_shard(na1, sa2)

        na2a_desc = yield drv.descriptor_factory("test_shard_notif_agent",
                                                 shard=u"shard2")
        na2a = yield agency2.start_agent(na2a_desc)

        yield self.wait_for_idle(10)

        check_no_changes(na2a)

        na2b_desc = yield drv.descriptor_factory("test_shard_notif_agent",
                                                 shard=u"shard2")
        na2b = yield agency2.start_agent(na2b_desc)

        yield self.wait_for_idle(10)

        check_no_changes(na2b)

        agency3 = yield drv.spawn_agency(start_host=False)
        sa3_desc = yield drv.descriptor_factory("shard_agent",
                                                shard=u"shard3")
        sa3 = yield agency3.start_agent(sa3_desc)

        yield self.wait_for_idle(10)

        check_new_shard(na1, sa3)
        check_new_shard(na2a, sa3)
        check_new_shard(na2b, sa3)

        na3_desc = yield drv.descriptor_factory("test_shard_notif_agent",
                                                shard=u"shard3")
        na3 = yield agency3.start_agent(na3_desc)

        yield self.wait_for_idle(10)

        check_no_changes(na3)

        sa1.terminate()

        yield self.wait_for_idle(50)

        check_shard_gone(na1, sa2, sa3)
        check_shard_gone(na2a, sa1)
        check_shard_gone(na2b, sa1)
        check_shard_gone(na3, sa1)
