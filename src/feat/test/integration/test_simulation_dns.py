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
from twisted.trial.unittest import FailTest

from feat.test.integration import common

from feat.agents.base import agent, descriptor, replay, resource
from feat.agents.common import dns, host
from feat.agents.dns import api, dns_agent
from feat.agents.dns.dns_agent import DnsName

from feat.database.interface import NotFoundError
from feat.models import reference, response
from feat.agents.application import feat

from feat.common import defer

from feat.interface.agent import Address


@feat.register_descriptor("dns_test_agent")
class Descriptor(descriptor.Descriptor):
    pass


@feat.register_agent("dns_test_agent")
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

    @defer.inlineCallbacks
    def prolog(self):
        agency = yield self.driver.spawn_agency(start_host=False)
        agency.disable_protocol('setup-monitoring', 'Task')
        d1 = yield self.driver.descriptor_factory('dns_test_agent')
        d2 = yield self.driver.descriptor_factory('dns_test_agent')
        d3 = yield self.driver.descriptor_factory('dns_test_agent')
        res = dict(dns=resource.AllocatedRange([8053]))
        d4 = yield self.driver.descriptor_factory('dns_agent',
                                                  ns='my.ns1.lan',
                                                  resources=res,
                                                  suffix='test.lan')
        d5 = yield self.driver.descriptor_factory('dns_agent',
                                                  ns='my.ns2.lan',
                                                  ns_ttl=42,
                                                  resources=res,
                                                  suffix='test.lan')
        m1 = yield agency.start_agent(d1, prefix='foo.bar', ip='192.168.0.1')
        m2 = yield agency.start_agent(d2,
                                      prefix='spam.beans', ip='192.168.0.2')
        m3 = yield agency.start_agent(d3,
                                      prefix='spam.beans', ip='192.168.0.3')
        m4 = yield agency.start_agent(d4)
        m5 = yield agency.start_agent(d5)

        self.agent1 = m1.get_agent()
        self.agent2 = m2.get_agent()
        self.agent3 = m3.get_agent()
        self.dns1 = m4.get_agent()
        self.dns2 = m5.get_agent()
        yield self.wait_for_idle(10)

    @defer.inlineCallbacks
    def testNSLookup(self):
        dns1 = self.dns1
        ns, ttl = yield dns1.lookup_ns("spam")
        self.assertEqual(ns, "my.ns1.lan")
        self.assertEqual(ttl, 300)

        dns2 = self.dns2
        ns, ttl = yield dns2.lookup_ns("spam")
        self.assertEqual(ns, "my.ns2.lan")
        self.assertEqual(ttl, 42)

    @defer.inlineCallbacks
    def testAddressMapping(self):
        dns = self.dns1
        yield dns.remove_mapping("not.existing", "0.0.0.0")
        yield self.assert_not_resolves('not.existing.test.lan', "0.0.0.0")
        yield dns.add_mapping("dummy", "123.45.67.89")
        yield self.assert_resolves('dummy.test.lan', "123.45.67.89")
        yield dns.add_mapping("dummy", "123.45.67.89")
        yield self.assert_resolves('dummy.test.lan', "123.45.67.89")
        yield dns.remove_mapping("dummy", "0.0.0.0")
        yield self.assert_resolves('dummy.test.lan', "123.45.67.89")
        yield dns.remove_mapping("dummy", "123.45.67.89")
        yield self.assert_not_resolves('dummy.test.lan', "123.45.67.89")

    @defer.inlineCallbacks
    def assert_resolves(self, name, ip):
        doc_id = DnsName.name_to_id(name)
        try:
            doc = yield self.driver.get_document(doc_id)
        except NotFoundError:
            raise FailTest("Document id: %s not found, asserting for ip: %r"
                           % (doc_id, ip))
        self.assertTrue([x for x in doc.entries if x.ip == ip],
                        "name %s doesn't resolve to %s" % (name, ip, ))

    @defer.inlineCallbacks
    def assert_not_resolves(self, name, ip):

        try:
            doc = yield self.driver.get_document(DnsName.name_to_id(name))
        except NotFoundError:
            pass
        else:
            self.assertFalse([x for x in doc.entries if x.ip == ip],
                             "Name %s resolves to %s. Entries: %r" %
                             (name, ip, doc.entries, ))

    @defer.inlineCallbacks
    def testAliases(self):
        dns = self.dns1
        yield dns.add_alias("dummy", "mycname.example.com")
        yield self.assert_resolves('dummy.test.lan', "mycname.example.com")
        yield dns.add_alias("dummy", "mycname.example.com")
        yield self.assert_resolves('dummy.test.lan', "mycname.example.com")
        yield dns.add_alias("2aliases", "mycname.example.com")
        yield self.assert_resolves('2aliases.test.lan', "mycname.example.com")
        # the folliowing call should overwrite the alias
        yield dns.add_alias("dummy", "error.example.com")
        yield self.assert_not_resolves('dummy.test.lan', "mycname.example.com")
        yield self.assert_resolves('dummy.test.lan', "error.example.com")
        yield dns.remove_alias("dummy", "error.example.com")
        yield self.assert_not_resolves('dummy.test.lan', "mycname.example.com")
        yield self.assert_not_resolves('dummy.test.lan', "error.example.com")

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

        agent1 = self.agent1
        agent2 = self.agent2
        agent3 = self.agent3

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

        agent1 = self.agent1
        agent2 = self.agent2
        agent3 = self.agent3

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

        def assertAlias(name, expected, exp_ttl = 300):
            for dns_medium in self.driver.iter_agents("dns_agent"):
                dns_agent = dns_medium.get_agent()
                alias, _ = dns_agent.lookup_alias(name)
                self.assertEqual(expected, alias)

        agent1 = self.agent1
        agent2 = self.agent2

        assertAlias("", None)
        assertAlias("foo.bar.test.lan", None)
        assertAlias("spam.beans.test.lan", None)

        # Test mapping addition

        yield agent1.register_alias()
        assertAlias("foo.bar.test.lan", "foo.bar.example.lan")

        yield agent2.register_alias()
        assertAlias("foo.bar.test.lan", "foo.bar.example.lan")
        assertAlias("spam.beans.test.lan", "spam.beans.example.lan")


        ## Test mapping multiple addition

        yield agent1.register_alias()
        assertAlias("foo.bar.test.lan", "foo.bar.example.lan")

        # Test mapping removal

        yield agent1.unregister_alias()
        assertAlias("foo.bar.test.lan", None)
        assertAlias("spam.beans.test.lan", "spam.beans.example.lan")

        yield agent2.unregister_alias()
        assertAlias("foo.bar.test.lan", None)
        assertAlias("spam.beans.test.lan", None)

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

        agent1 = self.agent1
        agent2 = self.agent2

        yield assertAlias("", None)
        yield assertAlias("foo.bar.test.lan", None)
        yield assertAlias("spam.beans.test.lan", None)

        # Test mapping addition

        yield agent1.register_alias_with_mapper()
        yield self.wait_for_idle(10)
        yield assertAlias("foo.bar.test.lan", "foo.bar.example.lan")

        yield agent2.register_alias_with_mapper()
        yield self.wait_for_idle(10)
        yield assertAlias("foo.bar.test.lan", "foo.bar.example.lan")
        yield assertAlias("spam.beans.test.lan", "spam.beans.example.lan")


        ## Test mapping multiple addition

        yield agent1.register_alias_with_mapper()
        yield self.wait_for_idle(10)
        yield assertAlias("foo.bar.test.lan", "foo.bar.example.lan")

        # Test mapping removal
        yield agent1.unregister_alias_with_mapper()
        yield self.wait_for_idle(10)
        yield assertAlias("foo.bar.test.lan", None)
        yield assertAlias("spam.beans.test.lan", "spam.beans.example.lan")

        yield agent2.unregister_alias_with_mapper()
        yield self.wait_for_idle(10)
        yield assertAlias("foo.bar.test.lan", None)
        yield assertAlias("spam.beans.test.lan", None)

        # Test multiple removal

        yield agent2.unregister_alias_with_mapper()
        yield self.wait_for_idle(10)


@common.attr(timescale=0.1)
class ExternalApiTest(common.SimulationTest, common.ModelTestMixin):

    @defer.inlineCallbacks
    def prolog(self):
        hostdef = host.HostDef()
        hostdef.categories['address'] = Address.fixed
        hostdef.ports_ranges['dns'] = (5000, 5010)
        self.hostdef = hostdef

        self.agency = yield self.driver.spawn_agency(
            hostdef=hostdef, hostname='host1.test.lan')
        yield self.wait_for_idle(15)

    @defer.inlineCallbacks
    def _assert_address(self, name, expected, exp_ttl = 300):
        yield common.delay(None, 0.1)
        for dns_medium in self.driver.iter_agents("dns_agent"):
            dns_agent = dns_medium.get_agent()
            result = yield dns_agent.lookup_address(name, "127.0.0.1")
            for ip, ttl in result:
                self.assertEqual(exp_ttl, ttl)
            self.assertEqual(set(expected),
                             set([ip for ip, _ttl in result]))

    @defer.inlineCallbacks
    def _assert_alias(self, name, expected, exp_ttl = 300):
        yield common.delay(None, 0.1)
        for dns_medium in self.driver.iter_agents("dns_agent"):
            dns_agent = dns_medium.get_agent()
            alias, _ = yield dns_agent.lookup_alias(name)
            self.assertEqual(expected, alias)

    @defer.inlineCallbacks
    def testPlayingWithApi(self):
        # start new dns agent by api call
        model = api.Root(self.agency)
        submodel = yield self.model_descend(model, 'servers')
        self.info('spawning dns agent')
        res = yield submodel.perform_action('post', suffix=u'test.lan')
        self.assertEqual(1, self.count_agents('dns_agent'))
        yield self.wait_for_idle(10)

        # check that locating from different agency works fine
        self.agency2 = yield self.driver.spawn_agency(
            hostdef=self.hostdef, hostname='host2.test.lan')

        model = api.Root(self.agency2)
        yield self.validate_model_tree(model)
        ref = yield self.model_descend(model, 'entries')
        items = yield ref.fetch_items()

        ref = yield self.model_descend(model, 'entries', 'test.lan')
        self.assertIsInstance(ref, reference.Absolute)

        # check non existing suffix
        ref = yield self.model_descend(model, 'entries', 'nonexisting')
        self.assertIs(None, ref)

        # now fetch the model from right agency and add some entries
        model = api.Root(self.agency)
        yield self.validate_model_tree(model)
        suffix_model = yield self.model_descend(model, 'entries', 'test.lan')
        self.assertIsInstance(suffix_model, api.EntrySuffix)

        # create entry
        resp = yield suffix_model.perform_action(
            'post', prefix='prefix', type='record_A', entry='1.2.3.4')
        self.assertIsInstance(resp, response.Created)

        yield self._assert_address("prefix.test.lan", ["1.2.3.4"])
        # add another one
        resp = yield suffix_model.perform_action(
            'post', prefix='prefix', type='record_A', entry='1.2.3.5')
        yield self._assert_address("prefix.test.lan", ["1.2.3.4", '1.2.3.5'])

        # now delete first entry
        suffix_model = yield self.model_descend(model, 'entries', 'test.lan')
        entry_model = yield self.model_descend(suffix_model, 'prefix',
                                               '1.2.3.4')
        resp = yield entry_model.perform_action('del')
        self.assertIsInstance(resp, response.Deleted)
        yield self._assert_address("prefix.test.lan", ['1.2.3.5'])

        # now add alias
        resp = yield suffix_model.perform_action(
            'post', prefix='prefix', type='record_CNAME', entry='google.com')
        yield self._assert_address("prefix.test.lan", [])
        yield self._assert_alias("prefix.test.lan", 'google.com')

        # and delete it
        entry_model = yield self.model_descend(suffix_model, 'prefix',
                                               'google.com')
        yield entry_model.perform_action('del')
        yield self._assert_alias("prefix.test.lan", None)

        # remove dns agent
        agent_model = yield self.model_descend(model, 'servers', 'dns_agent_1')
        yield agent_model.perform_action('del')
        yield self.wait_for_idle(10)
        self.assertEqual(0, self.count_agents('dns_agent'))
