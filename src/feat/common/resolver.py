from twisted.names import client, resolve, cache, hosts as hostsModule


class Resolver(client.Resolver):

    def getHostByName(self, name, timeout = None, effort = 10):
        """
        Overwrite this method to use A type query instead of ANY
        which is done by default by the resolver.
        """
        d = self.lookupAddress(name, timeout)
        d.addCallback(self._cbRecords, name, effort)
        return d


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
