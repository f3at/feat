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

from feat.agencies import recipient
from feat.agents.base import requester, problem
from feat.agents.host import host_agent
from feat.agents.common import host as chost
from feat.agents.common import shard as cshard
from feat.test.dummies import DummyMedium

from . import common


class DummyHostMedium(DummyMedium):

    hosted = False

    def __init__(self, logger):
        self.agent = None
        DummyMedium.__init__(self, logger)

    def check_if_hosted(self, recp):
        return self.hosted


class AlerterStub(object):

    recipients = None

    def update_recipients(self, recp):
        self.recipients = recp


class TestDNSAgentLabour(common.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        self.medium = DummyHostMedium(self)
        self.host = host_agent.HostAgent(self.medium)
        self.medium.agent = self.host
        self.shardPartner = host_agent.ShardPartner(self.host)
        yield

    @defer.inlineCallbacks
    def testInitiateWithoutResources(self):
        hostdef = chost.HostDef(resources={}, categories={}, ports_ranges={})
        yield self.host.initiate(hostdef=hostdef)

    @defer.inlineCallbacks
    def testInitiateWithDefaultResources(self):
        yield self.host.initiate()

    @defer.inlineCallbacks
    def testSwitchShard(self):
        stub = AlerterStub()
        self.host._get_state().alerter = stub
        yield self.host.switch_shard("NewShard")
        desc = self.medium.get_descriptor()
        self.assertEquals(desc.shard, 'NewShard')
        # Switching to same shard should give the same result
        yield self.host.switch_shard("NewShard")
        desc = self.medium.get_descriptor()
        self.assertEquals(desc.shard, 'NewShard')

        self.assertEqual('NewShard', stub.recipients.route)

    @defer.inlineCallbacks
    def testCreatePartner(self):
        recp = recipient.Recipient(23, 'NewPartner')
        yield self.host.create_partner(host_agent.ShardPartner, recp)
        desc = self.medium.get_descriptor()
        self.assertEquals(recp, desc.partners[0].recipient)

    def testStartAgent(self):
        desc = chost.Descriptor()
        self.host.start_agent(self.host, desc)
        self.assertEquals(self.medium.protocols[-1].factory,
                          host_agent.StartAgent)

    def testStartOwnShard(self):
        desc = cshard.Descriptor()
        self.host.start_own_shard(desc)
        self.assertEquals(self.medium.protocols[-1].factory,
                          host_agent.StartAgent)

    def testStartJoinShardManager(self):
        self.host.start_join_shard_manager()
        self.assertEquals(self.medium.protocols[-1].factory,
                          host_agent.StartAgent)

    def testGetIP(self):
        ip = self.host.get_ip()
        self.assertEquals(ip, '127.0.0.1')

    @defer.inlineCallbacks
    def testShardPartner(self):
        yield self.host._get_state().partners.update_partner(self.shardPartner)
        shard = yield self.host.get_shard_partner().start()
        self.assertEquals(shard, self.shardPartner)

    def testResolveMissingShardProblem(self):
        self.host.resolve_missing_shard_agent_problem([])
        self.assertEquals(problem.CollectiveSolver,
                          self.medium.protocols[0].factory)

    @defer.inlineCallbacks
    def testAgencyHosts(self):
        recp = recipient.Recipient(23, 'NewPartner')
        yield self.host.create_partner(host_agent.ShardPartner, recp)

        self.medium.hosted = True
        self.host.check_if_agency_hosts(recp)
        desc = self.medium.get_descriptor()
        self.assertEquals(desc.partners[0].recipient, recp)

        self.medium.hosted = False
        self.host.check_if_agency_hosts(recp)
        self.assertEquals(self.medium.protocols[0].factory,
                          requester.PartnershipProtocol)
