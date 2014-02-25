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
import socket

from twisted.internet import defer
from twisted.names import client, dns

from feat.agents.base import resource
from feat.agencies import message
from feat.agents.dns import dns_agent, production
from feat.common import log, guard
from feat.test.dummies import DummyMedium

from feat.agents.dns.interface import RecordA, RecordCNAME

from . import common


class TestDNSAgentLabour(common.TestCase):

    @defer.inlineCallbacks
    def testNSQueries(self):

        @defer.inlineCallbacks
        def check(exp_ns, exp_ttl, suffix='mydomain.lan', ns_ttl=300):
            notify = dns_agent.NotifyConfiguration()

            patron = log.LogProxy(self)
            labour = production.Labour(
                patron, notify, suffix, '127.0.0.1', 'ns.' + suffix, ns_ttl)

            res = labour.startup(0)
            self.assertTrue(res)
            address = labour.get_host()
            port = address.port
            cresolver = client.Resolver(servers=[("127.0.0.1", port)])
            res = yield cresolver.queryUDP(
                [dns.Query(suffix, dns.NS)])
            self.assertEqual(len(res.answers), 1)
            answer = res.answers[0]
            self.assertEqual(answer.ttl, exp_ttl)
            payload = answer.payload
            self.assertEqual(payload.TYPE, dns.NS)
            self.assertEqual(payload.name.name, exp_ns)
            yield labour.cleanup()

        yield check("ns.mydomain.lan", 300)
        yield check("ns.mydomain.lan", 42, ns_ttl=42)
        yield check("ns.spam.lan", 300, suffix="spam.lan")

    @defer.inlineCallbacks
    def testCNAMEQueries(self):

        @defer.inlineCallbacks
        def check(name, alias, exp_ttl, aa_ttl=300):
            notify = dns_agent.NotifyConfiguration()
            suffix='mydomain.lan'
            ns_ttl=300
            patron = log.LogProxy(self)
            labour = production.Labour(
                patron, notify, suffix, '127.0.0.1', 'ns.' + suffix, ns_ttl)

            res = labour.startup(0)
            self.assertTrue(res)

            name = format_name(name, suffix)
            record = RecordCNAME(ip=name, ttl=aa_ttl)
            labour.update_records(name, [record])

            address = labour.get_host()
            port = address.port
            cresolver = client.Resolver(servers=[("127.0.0.1", port)])
            res = yield cresolver.queryUDP([dns.Query(alias, dns.CNAME)])
            for answer in res.answers:
                self.assertEqual(answer.ttl, exp_ttl)
                payload = answer.payload
                self.assertEqual(payload.TYPE, dns.CNAME)
                self.assertEqual(str(payload.name), name)
            yield labour.cleanup()

        yield check("spam", 'cname.example.com', 300)
        yield check("spam", 'cname.example.com', 42, aa_ttl=42)

    @defer.inlineCallbacks
    def testAQueries(self):

        @defer.inlineCallbacks
        def check(name, exp_ips, exp_ttl, aa_ttl=300):
            notify = dns_agent.NotifyConfiguration()
            suffix='mydomain.lan'
            ns_ttl=300

            name = format_name(name, suffix)

            patron = log.LogProxy(self)
            labour = production.Labour(
                patron, notify, suffix, '127.0.0.1', 'ns.' + suffix, ns_ttl)

            res = labour.startup(0)
            self.assertTrue(res)

            records = [RecordA(ttl=aa_ttl, ip=ip)
                       for ip in exp_ips]
            labour.update_records(name, records)

            address = labour.get_host()
            port = address.port
            cresolver = client.Resolver(servers=[("127.0.0.1", port)])
            res = yield cresolver.queryUDP([dns.Query(name, dns.A)])
            result = []
            for answer in res.answers:
                self.assertEqual(answer.ttl, exp_ttl)
                payload = answer.payload
                self.assertEqual(payload.TYPE, dns.A)
                result.append(socket.inet_ntoa(payload.address))
            self.assertEqual(exp_ips, result)
            yield labour.cleanup()

        yield check("spam", [], 300)
        yield check("spam", ["192.168.0.1"], 300)
        yield check("spam", ["192.168.0.1"], 42, aa_ttl=42)
        yield check("spam", ["192.168.0.1", "192.168.0.2"], 300)


class TestDNSAgentMisc(common.TestCase):

    def testDnsName(self):
        self.assertEquals(
            dns_agent.DnsName.name_to_id('test'), 'dns_test')
        self.assertEquals(
            dns_agent.DnsName.id_to_name('dns_guainch'), 'guainch')
        self.failUnlessRaises(AttributeError,
            dns_agent.DnsName.id_to_name, 'jau')

    def testView(self):
        name = {'_id': '1', '.type': 'dns_name',
                'zone': 'test.lan', 'name': 'jander'}
        view = dns_agent.DnsView

        self.assertEquals(list(view.perform_map(name))[0],
                          (name['zone'], None))
        query1 = {'query': {'zone': 'test.lan'}}
        query2 = {'query': {'zone': 'test1.lan'}}
        self.assertTrue(view.perform_filter(name, query1))
        self.assertFalse(view.perform_filter(name, query2))


class DummyDNSMedium(DummyMedium):

    def get_configuration(self):
        return dns_agent.DNSAgentConfiguration(suffix='lan')

    def descriptor_class(self, **kwargs):
        desc = dns_agent.Descriptor(**kwargs)
        desc.resources = {'dns': resource.AllocatedRange([53])}
        return desc


@common.attr('slow', timeout=40)
class TestDNSAgent(common.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        self.medium = DummyDNSMedium(self)
        self.dns = dns_agent.DNSAgent(self.medium)
        self.collector = \
            dns_agent.MappingUpdatesCollector(self.dns, self.medium)

        yield self.dns.initiate()
        yield self.dns.startup()

    def _notify(self, action, *args):
        msg = message.BaseMessage(payload=[action, args])
        self.collector.notified(msg)

    @defer.inlineCallbacks
    def testMappings(self):
        # Add mapping
        yield self.dns.add_mapping('test', '1.1.1.1')
        yield common.delay(None, 0.01)
        # Resolve mapping
        a = yield self.dns.lookup_address('test.lan', '')
        self.assertEquals(a[0][0], '1.1.1.1')
        # Add duplicated mapping
        yield self.dns.add_mapping('test', '1.1.1.1')
        # Remove mapping
        yield self.dns.remove_mapping('test', '1.1.1.1')
        yield common.delay(None, 0.01)
        a = yield self.dns.lookup_address('test.lan', '')
        self.assertEquals(a, [])

        # Remove again the mapping
        yield self.dns.remove_mapping('test', '1.1.1.1')
        # Remove wrong mapping
        yield self.dns.remove_mapping('test', '1.1.1.2')

    @defer.inlineCallbacks
    def testAlias(self):
        # Add alias
        yield self.dns.add_alias('dog', '1.1.1.2')
        # Resolve alias
        yield common.delay(None, 0.01)
        a = yield self.dns.lookup_alias('dog.lan')
        self.assertEquals(a[0], '1.1.1.2')
        # Remove alias
        yield self.dns.remove_alias('dog', '1.1.1.2')
        yield common.delay(None, 0.01)
        a = yield self.dns.lookup_alias('dog')
        # Remove alias again
        yield self.dns.remove_alias('dog', '1.1.1.2')
        self.assertEquals(a, (None, None))
        # Add same alias for different ips
        yield self.dns.add_alias('dog', '1.1.1.2')
        yield self.dns.add_alias('dog', '1.1.1.1')

    def testSuffix(self):
        self.assertTrue(self.dns.get_suffix(), 'lan')

    def testNS(self):
        self.assertTrue(self.dns.lookup_ns('test.lan'), '')

    def testUpdates(self):
        defer.setDebugging=True
        self._notify('add_mapping', 'test', '1.1.1.1')
        self._notify('remove_mapping', 'test', '1.1.1.1')
        self._notify('add_alias', 'test', 'dog')
        self._notify('remove_alias', 'test', 'dog')
        # Try with an uknown action
        self._notify('remove_beach', 'test', 'dog')


def format_name(prefix, suffix):
    return prefix + '.' + suffix
