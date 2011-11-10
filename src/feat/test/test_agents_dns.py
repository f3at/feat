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

from feat.agents.dns import dns_agent, production
from feat.common import log

from feat.agents.dns.interface import RecordA, RecordCNAME

from . import common


class TestDNSAgent(common.TestCase):

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


def format_name(prefix, suffix):
    return prefix + '.' + suffix
