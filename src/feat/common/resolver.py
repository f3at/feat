import socket

from twisted.names import dns, client, resolve, cache, hosts as hostsModule
from twisted.internet import error


def installResolver(reactor=None,
                    resolv='/etc/resolv.conf',
                    servers=[],
                    hosts='/etc/hosts'):
    theResolver = Resolver(resolv, servers)
    hostResolver = hostsModule.Resolver(hosts)
    L = [hostResolver, cache.CacheResolver(), theResolver]
    if reactor is None:
        from twisted.internet import reactor
    reactor.installResolver(resolve.ResolverChain(L))


class Resolver(client.Resolver):

    def getHostByName(self, name, timeout = None, effort = 10):
        """
        Overwrite this method to use A type query instead of ANY
        which is done by default by the resolver.
        """
        d = self.lookupAddress(name, timeout)
        d.addCallback(self._cbRecords, name, effort)
        return d

    def _cbRecords(self, (ans, auth, add), name, effort):
        result = extractRecord(self, dns.Name(name), ans + auth + add, effort)
        if not result:
            raise error.DNSLookupError(name)
        return result


def extractRecord(resolver, name, answers, level=10):
    '''
    This method is copy-pasted from twisted.names.common.
    The difference with the original is, that it favors IPv4 responses over
    IPv6. This is motivated by the problem of resolving "maps.googleapis.com"
    name, which has both types of entries.
    The logic in twisted.internet.tcp.Connector assumes the IPv4 type of
    address, and it fails to connect if IPv6 address is given.
    This problem only occurs with Twisted 10.2. In 12.1 the Connector
    implementation can already handle both types of addresses.
    '''

    if not level:
        return None
    for r in answers:
        if r.name == name and r.type == dns.A:
            return socket.inet_ntop(socket.AF_INET, r.payload.address)
    for r in answers:
        if r.name == name and r.type == dns.CNAME:
            result = extractRecord(
                resolver, r.payload.name, answers, level - 1)
            if not result:
                return resolver.getHostByName(
                    str(r.payload.name), effort=level - 1)
            return result
    if hasattr(socket, 'inet_ntop'):
        for r in answers:
            if r.name == name and r.type == dns.A6:
                return socket.inet_ntop(socket.AF_INET6, r.payload.address)
        for r in answers:
            if r.name == name and r.type == dns.AAAA:
                return socket.inet_ntop(socket.AF_INET6, r.payload.address)
    # No answers, but maybe there's a hint at who we should be asking about
    # this
    for r in answers:
        if r.type == dns.NS:
            r = Resolver(servers=[(str(r.payload.name), dns.PORT)])
            d = r.lookupAddress(str(name))
            d.addCallback(lambda (ans, auth, add):
                          extractRecord(r, name, ans + auth + add, level - 1))
            return d
