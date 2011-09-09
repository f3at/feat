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
from twisted.python import failure

from feat.test.integration import common

from feat.agents.base import agent, descriptor, replay
from feat.agents.common import dns
from feat.agents.dns import dns_agent
from feat.common import defer
from feat.common.text_helper import format_block

from feat.interface.recipient import *


@descriptor.register("dns_test_agent")
class Descriptor(descriptor.Descriptor):
    pass


@agent.register("dns_test_agent")
class Agent(agent.BaseAgent):

    @replay.mutable
    def initiate(self, state, prefix, ip):
        state.prefix = prefix
        state.ip = ip
        state.alias = '%s.example.lan' % prefix
        state.mapper = dns.new_mapper(self)

    @replay.mutable
    def register(self, state):
        return dns.add_mapping(self, state.prefix, state.ip)

    @replay.mutable
    def unregister(self, state):
        return dns.remove_mapping(self, state.prefix, state.ip)

    @replay.mutable
    def do_remove(self, state, prefix, ip):
        return dns.remove_mapping(self, prefix, ip)

    @replay.mutable
    def do_add(self, state, prefix, ip):
        return dns.add_mapping(self, prefix, ip)

    @replay.mutable
    def register_with_mapper(self, state):
        return state.mapper.add_mapping(state.prefix, state.ip)

    @replay.mutable
    def unregister_with_mapper(self, state):
        return state.mapper.remove_mapping(state.prefix, state.ip)

    @replay.mutable
    def do_remove_with_mapper(self, state, prefix, ip):
        return state.mapper.remove_mapping(prefix, ip)

    @replay.mutable
    def do_add_with_mapper(self, state, prefix, ip):
        return state.mapper.add_mapping(prefix, ip)

    @replay.mutable
    def register_alias_with_mapper(self, state):
        return state.mapper.add_alias(state.prefix, state.alias)

    @replay.mutable
    def unregister_alias_with_mapper(self, state):
        return state.mapper.remove_alias(state.prefix, state.alias)

    @replay.mutable
    def register_alias(self, state):
        return dns.add_alias(self, state.prefix, state.alias)

    @replay.mutable
    def unregister_alias(self, state):
        return dns.remove_alias(self, state.prefix, state.alias)


@common.attr(timescale=0.1)
@common.attr('slow')
class DNSAgentTest(common.SimulationTest):

    def prolog(self):
        setup = format_block("""
        agency = spawn_agency()
        agency.disable_protocol('setup-monitoring', 'Task')
        d1 = descriptor_factory('dns_test_agent')
        d2 = descriptor_factory('dns_test_agent')
        d3 = descriptor_factory('dns_test_agent')
        d4 = descriptor_factory('dns_agent')
        d5 = descriptor_factory('dns_agent')
        m1 = agency.start_agent(d1, prefix='foo.bar', ip='192.168.0.1')
        m2 = agency.start_agent(d2, prefix='spam.beans', ip='192.168.0.2')
        m3 = agency.start_agent(d3, prefix='spam.beans', ip='192.168.0.3')
        m4 = agency.start_agent(d4, suffix='test.lan', ns='my.ns1.lan')
        m5 = agency.start_agent(d5, suffix='test.lan', \
                                ns='my.ns2.lan', ns_ttl=42)
        agent1 = m1.get_agent()
        agent2 = m2.get_agent()
        agent3 = m3.get_agent()
        dns1 = m4.get_agent()
        dns2 = m5.get_agent()
        """)
        return self.process(setup)

    def testValidateProlog(self):
        agents = list(self.driver.iter_agents("dns_test_agent"))
        dnss = list(self.driver.iter_agents("dns_agent"))
        self.assertEqual(3, len(agents))
        self.assertEqual(2, len(dnss))

    @defer.inlineCallbacks
    def testNSLookup(self):
        dns1 = self.get_local("dns1")
        ns, ttl = yield dns1.lookup_ns("spam")
        self.assertEqual(ns, "my.ns1.lan")
        self.assertEqual(ttl, 300)

        dns2 = self.get_local("dns2")
        ns, ttl = yield dns2.lookup_ns("spam")
        self.assertEqual(ns, "my.ns2.lan")
        self.assertEqual(ttl, 42)

    @defer.inlineCallbacks
    def testAddressMapping(self):
        dns = self.get_local("dns1")

        res = yield dns.remove_mapping("not.existing.test.lan", "0.0.0.0")
        self.assertFalse(res)
        res = yield dns.add_mapping("dummy.test.lan", "123.45.67.89")
        self.assertTrue(res)
        res = yield dns.add_mapping("dummy.test.lan", "123.45.67.89")
        self.assertFalse(res)
        res = yield dns.remove_mapping("dummy.test.lan", "0.0.0.0")
        self.assertFalse(res)
        res = yield dns.remove_mapping("dummy.test.lan", "123.45.67.89")
        self.assertTrue(res)

    @defer.inlineCallbacks
    def testAliases(self):
        dns = self.get_local("dns1")

        res = yield dns.remove_alias("dummy", "mycname.example.com")
        self.assertFalse(res)
        res = yield dns.add_alias("dummy", "mycname.example.com")
        self.assertTrue(res)
        res = yield dns.add_alias("dummy", "mycname.example.com")
        self.assertFalse(res)
        res = yield dns.add_alias("2aliases", "mycname.example.com")
        self.assertFalse(res)
        res = yield dns.remove_alias("dummy", "error.example.com")
        self.assertFalse(res)
        res = yield dns.remove_alias("dummy", "mycname.example.com")
        self.assertTrue(res)

    @defer.inlineCallbacks
    def testMappingBroadcast(self):

        @defer.inlineCallbacks
        def assertAddress(name, expected, exp_ttl = 300):
            for dns_medium in self.driver.iter_agents("dns_agent"):
                dns_agent = dns_medium.get_agent()
                result = yield dns_agent.lookup_address(name, "127.0.0.1")
                for ip, ttl in result:
                    self.assertEqual(exp_ttl, ttl)
                self.assertEqual(set(expected),
                                 set([ip for ip, _ttl in result]))

        agent1 = self.get_local("agent1")
        agent2 = self.get_local("agent2")
        agent3 = self.get_local("agent3")

        yield assertAddress("", [])
        yield assertAddress("foo.bar", [])
        yield assertAddress("spam.beans", [])
        yield assertAddress("foo.bar.test.lan", [])
        yield assertAddress("spam.beans.test.lan", [])

        # Test mapping addition

        yield agent1.register()
        yield assertAddress("foo.bar.test.lan", ["192.168.0.1"])
        yield assertAddress("spam.beans.test.lan", [])
        yield assertAddress("foo.bar", [])

        yield agent2.register()
        yield assertAddress("foo.bar.test.lan", ["192.168.0.1"])
        yield assertAddress("spam.beans.test.lan", ["192.168.0.2"])
        yield assertAddress("foo.bar", [])
        yield assertAddress("spam.beans", [])

        yield agent3.register()
        yield assertAddress("foo.bar.test.lan", ["192.168.0.1"])
        yield assertAddress("spam.beans.test.lan", ["192.168.0.3",
                                                    "192.168.0.2"])
        yield assertAddress("spam.beans.test.lan", ["192.168.0.2",
                                                    "192.168.0.3"])

        # Test mapping multiple addition

        yield agent1.register()
        yield assertAddress("foo.bar.test.lan", ["192.168.0.1"])

        # Test mapping removal

        yield agent1.unregister()
        yield assertAddress("foo.bar.test.lan", [])
        yield assertAddress("spam.beans.test.lan", ["192.168.0.3",
                                                    "192.168.0.2"])

        yield agent3.unregister()
        yield assertAddress("foo.bar.test.lan", [])
        yield assertAddress("spam.beans.test.lan", ["192.168.0.2"])

        yield agent2.unregister()
        yield assertAddress("foo.bar.test.lan", [])
        yield assertAddress("spam.beans.test.lan", [])


        # Test multiple removal

        yield agent2.unregister()

    @defer.inlineCallbacks
    def testMappingBroadcastWithNotification(self):

        @defer.inlineCallbacks
        def assertAddress(name, expected, exp_ttl = 300):
            for dns_medium in self.driver.iter_agents("dns_agent"):
                dns_agent = dns_medium.get_agent()
                result = yield dns_agent.lookup_address(name, "127.0.0.1")
                for ip, ttl in result:
                    self.assertEqual(exp_ttl, ttl)
                self.assertEqual(set(expected),
                                 set([ip for ip, _ttl in result]))

        agent1 = self.get_local("agent1")
        agent2 = self.get_local("agent2")
        agent3 = self.get_local("agent3")

        yield assertAddress("", [])
        yield assertAddress("foo.bar", [])
        yield assertAddress("spam.beans", [])
        yield assertAddress("foo.bar.test.lan", [])
        yield assertAddress("spam.beans.test.lan", [])

        # Test mapping addition

        yield agent1.register_with_mapper()
        yield self.wait_for_idle(10)
        yield assertAddress("foo.bar.test.lan", ["192.168.0.1"])
        yield assertAddress("spam.beans.test.lan", [])
        yield assertAddress("foo.bar", [])

        yield agent2.register_with_mapper()
        yield self.wait_for_idle(10)
        yield assertAddress("foo.bar.test.lan", ["192.168.0.1"])
        yield assertAddress("spam.beans.test.lan", ["192.168.0.2"])
        yield assertAddress("foo.bar", [])
        yield assertAddress("spam.beans", [])

        yield agent3.register_with_mapper()
        yield self.wait_for_idle(10)
        yield assertAddress("foo.bar.test.lan", ["192.168.0.1"])
        yield assertAddress("spam.beans.test.lan", ["192.168.0.3",
                                                    "192.168.0.2"])
        yield assertAddress("spam.beans.test.lan", ["192.168.0.2",
                                                    "192.168.0.3"])

        # Test mapping multiple addition

        yield agent1.register_with_mapper()
        yield self.wait_for_idle(10)
        yield assertAddress("foo.bar.test.lan", ["192.168.0.1"])

        # Test mapping removal

        yield agent1.unregister_with_mapper()
        yield self.wait_for_idle(10)
        yield assertAddress("foo.bar.test.lan", [])
        yield assertAddress("spam.beans.test.lan", ["192.168.0.3",
                                                    "192.168.0.2"])

        yield agent3.unregister_with_mapper()
        yield self.wait_for_idle(10)
        yield assertAddress("foo.bar.test.lan", [])
        yield assertAddress("spam.beans.test.lan", ["192.168.0.2"])

        yield agent2.unregister_with_mapper()
        yield self.wait_for_idle(10)
        yield assertAddress("foo.bar.test.lan", [])
        yield assertAddress("spam.beans.test.lan", [])


        # Test multiple removal

        yield agent2.unregister_with_mapper()
        yield self.wait_for_idle(10)

    @defer.inlineCallbacks
    def testAliasMappingBroadcast(self):

        @defer.inlineCallbacks
        def assertAlias(name, expected, exp_ttl = 300):
            for dns_medium in self.driver.iter_agents("dns_agent"):
                dns_agent = dns_medium.get_agent()
                alias, _ = yield dns_agent.lookup_alias(name)
                self.assertEqual(expected, alias)

        agent1 = self.get_local("agent1")
        agent2 = self.get_local("agent2")

        yield assertAlias("", None)
        yield assertAlias("foo.bar.example.lan", None)
        yield assertAlias("spam.beans.example.lan", None)

        # Test mapping addition

        yield agent1.register_alias()
        yield assertAlias("foo.bar.example.lan", "foo.bar.test.lan")

        yield agent2.register_alias()
        yield assertAlias("foo.bar.example.lan", "foo.bar.test.lan")
        yield assertAlias("spam.beans.example.lan", "spam.beans.test.lan")


        ## Test mapping multiple addition

        yield agent1.register_alias()
        yield assertAlias("foo.bar.example.lan", "foo.bar.test.lan")

        # Test mapping removal

        yield agent1.unregister_alias()
        yield assertAlias("foo.bar.example.lan", None)
        yield assertAlias("spam.beans.example.lan", "spam.beans.test.lan")

        yield agent2.unregister_alias()
        yield assertAlias("foo.bar.example.lan", None)
        yield assertAlias("spam.beans.example.lan", None)

        # Test multiple removal

        yield agent2.unregister_alias()

    @defer.inlineCallbacks
    def testAliasMappingBroadcastWithNotification(self):

        @defer.inlineCallbacks
        def assertAlias(name, expected, exp_ttl = 300):
            for dns_medium in self.driver.iter_agents("dns_agent"):
                dns_agent = dns_medium.get_agent()
                alias, _ = yield dns_agent.lookup_alias(name)
                self.assertEqual(expected, alias)

        agent1 = self.get_local("agent1")
        agent2 = self.get_local("agent2")

        yield assertAlias("", None)
        yield assertAlias("foo.bar.example.lan", None)
        yield assertAlias("spam.beans.example.lan", None)

        # Test mapping addition

        yield agent1.register_alias_with_mapper()
        yield self.wait_for_idle(10)
        yield assertAlias("foo.bar.example.lan", "foo.bar.test.lan")

        yield agent2.register_alias_with_mapper()
        yield self.wait_for_idle(10)
        yield assertAlias("foo.bar.example.lan", "foo.bar.test.lan")
        yield assertAlias("spam.beans.example.lan", "spam.beans.test.lan")


        ## Test mapping multiple addition

        yield agent1.register_alias_with_mapper()
        yield self.wait_for_idle(10)
        yield assertAlias("foo.bar.example.lan", "foo.bar.test.lan")

        # Test mapping removal

        yield agent1.unregister_alias_with_mapper()
        yield self.wait_for_idle(10)
        yield assertAlias("foo.bar.example.lan", None)
        yield assertAlias("spam.beans.example.lan", "spam.beans.test.lan")

        yield agent2.unregister_alias_with_mapper()
        yield self.wait_for_idle(10)
        yield assertAlias("foo.bar.example.lan", None)
        yield assertAlias("spam.beans.example.lan", None)


        # Test multiple removal

        yield agent2.unregister_alias_with_mapper()
        yield self.wait_for_idle(10)
