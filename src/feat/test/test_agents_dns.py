import socket

from twisted.internet import defer
from twisted.names import client, dns
from zope.interface import implements

from feat.agents.dns import dns_agent, production
from feat.agents.dns.labour import *

from . import common


class DummyPatron(object):

    implements(IDNSServerPatron)

    def __init__(self, aa_ttl=300, ns="ns.mydomain.lan",
                 ns_ttl=300, mapping={}):
        self._aa_ttl = aa_ttl
        self._mapping = mapping
        self._ns = ns
        self._ns_ttl = ns_ttl

    ### IDNSServerPatron Methods ###

    def lookup_address(self, name, address):
        return [(ip, self._aa_ttl) for ip in self._mapping.get(name, [])]

    def lookup_ns(self, name):
        return self._ns, self._ns_ttl


class TestDNSAgent(common.TestCase):

    @defer.inlineCallbacks
    def testNSQueries(self):

        @defer.inlineCallbacks
        def check(name, exp_ns, exp_ttl, **kwargs):
            patron = DummyPatron(**kwargs)
            labour = production.Labour(patron)
            labour.initiate()
            res = labour.startup(0)
            self.assertTrue(res)
            address = labour.get_host()
            port = address.port
            resolver = client.Resolver(servers=[("127.0.0.1", port)])
            res = yield resolver.queryUDP([dns.Query(name, dns.NS)])
            self.assertEqual(len(res.answers), 1)
            answer = res.answers[0]
            self.assertEqual(answer.ttl, exp_ttl)
            payload = answer.payload
            self.assertEqual(payload.TYPE, dns.NS)
            self.assertEqual(payload.name.name, exp_ns)
            yield labour.cleanup()

        yield check("spam", "ns.mydomain.lan", 300)
        yield check("spam", "ns.mydomain.lan", 42, ns_ttl=42)
        yield check("spam", "spam.lan", 300, ns="spam.lan")

    @defer.inlineCallbacks
    def testAQueries(self):

        @defer.inlineCallbacks
        def check(name, exp_ips, exp_ttl, **kwargs):
            patron = DummyPatron(**kwargs)
            labour = production.Labour(patron)
            labour.initiate()
            res = labour.startup(0)
            self.assertTrue(res)
            address = labour.get_host()
            port = address.port
            resolver = client.Resolver(servers=[("127.0.0.1", port)])
            res = yield resolver.queryUDP([dns.Query(name, dns.A)])
            result = []
            for answer in res.answers:
                self.assertEqual(answer.ttl, exp_ttl)
                payload = answer.payload
                self.assertEqual(payload.TYPE, dns.A)
                result.append(socket.inet_ntoa(payload.address))
            self.assertEqual(exp_ips, result)
            yield labour.cleanup()

        yield check("spam.lan", [], 300)
        yield check("spam.lan", ["192.168.0.1"], 300,
                    mapping={"spam.lan": ["192.168.0.1"]})
        yield check("spam.lan", ["192.168.0.1"], 42, aa_ttl=42,
                    mapping={"spam.lan": ["192.168.0.1"]})
        yield check("spam.lan", ["192.168.0.1", "192.168.0.2"], 300,
                    mapping={"spam.lan": ["192.168.0.1", "192.168.0.2"]})
