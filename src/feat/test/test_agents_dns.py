import socket

from twisted.internet import defer
from twisted.names import client, dns
from twisted.names import common as dns_common
from zope.interface import implements

from feat.agents.dns import dns_agent, production
from feat.common import log

from feat.agents.dns.interface import *

from . import common


class TestResolver(dns_agent.Resolver):

    def __init__(self, suffix='mydomain.lan', ns_ttl=300):
        self.suffix = suffix
        ns = 'ns.'+suffix
        host_ip='127.0.0.1'
        notify = dns_agent.NotifyConfiguration()
        dns_agent.Resolver.__init__(self, suffix, ns, notify, host_ip, ns_ttl)


class TestDNSAgent(common.TestCase):

    @defer.inlineCallbacks
    def testNSQueries(self):

        @defer.inlineCallbacks
        def check(exp_ns, exp_ttl, **kwargs):
            resolver = TestResolver(**kwargs)
            patron = log.LogProxy(self)
            labour = production.Labour(patron,
                                       resolver,
                                       slaves=[],
                                       suffix=resolver.suffix)
            labour.initiate()
            res = labour.startup(0)
            self.assertTrue(res)
            address = labour.get_host()
            port = address.port
            cresolver = client.Resolver(servers=[("127.0.0.1", port)])
            res = yield cresolver.queryUDP(
                [dns.Query(resolver.suffix, dns.NS)])
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
            resolver = TestResolver()
            name = resolver.format_name(name, resolver.suffix)
            resolver.add_record(alias, dns.Record_CNAME(name, aa_ttl))
            patron = log.LogProxy(self)
            labour = production.Labour(patron,
                                       resolver,
                                       slaves=[],
                                       suffix=resolver.suffix)
            labour.initiate()
            res = labour.startup(0)
            self.assertTrue(res)
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
            resolver = TestResolver()
            name = resolver.format_name(name, resolver.suffix)
            map(lambda ip: resolver.add_record(name,
                dns.Record_A(ip, aa_ttl)), exp_ips)
            patron = log.LogProxy(self)
            labour = production.Labour(patron,
                                       resolver,
                                       slaves=[],
                                       suffix=resolver.suffix)
            labour.initiate()
            res = labour.startup(0)
            self.assertTrue(res)
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
