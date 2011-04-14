from twisted.names import client, server, common, dns
from twisted.python import failure
from twisted.internet import reactor, error
from zope.interface import implements, classProvides

from feat.agents.base import replay
from feat.common import defer, serialization

from feat.agents.dns.labour import *


@serialization.register
class Labour(serialization.Serializable, EqualityMixin):

    classProvides(IDNSServerLabourFactory)
    implements(IDNSServerLabour)

    def __init__(self, patron):
        self._patron = patron
        self._resolver = Resolver(patron)
        self._listener = None

    @replay.side_effect
    def initiate(self):
        dns_fact = DNSServerFactory(clients=[self._resolver], verbose=0)
        udp_fact = dns.DNSDatagramProtocol(dns_fact)
        self._factory = udp_fact

    @replay.side_effect
    def startup(self, port):
        try:
            self._listener = reactor.listenUDP(port, self._factory)
            return True
        except error.CannotListenError:
            return False

    def cleanup(self):
        return self._listener.stopListening()

    def get_host(self):
        return self._listener and self._listener.getHost()


class Resolver(common.ResolverBase):

    def __init__(self, patron):
        common.ResolverBase.__init__(self)
        self._patron = IDNSServerPatron(patron)

    ### IResolver Methods ###

    def query(self, query, address, timeout=None):
        '''Interpret and delegate the query to the parent labour.
        The interface has been modified to take the address as an
        extra parameter, it need a modified factory to work.'''

        def package_response(response, name, rec_type):
            results = []

            if not isinstance(response, list):
                response = [response] if response is not None else []

            for rec in response:
                record = rec_type(*rec)
                header = dns.RRHeader(name, record.TYPE, dns.IN,
                                      record.ttl, record, auth=True)
                results.append(header)

            if not results:
                raise dns.DomainError(name)

            return results, [], []

        name = str(query.name)

        if query.type == dns.A:
            d = defer.succeed(name)
            d.addCallback(self._patron.lookup_address, address[0])
            d.addCallback(package_response, name, dns.Record_A)
            return d

        if query.type == dns.NS:
            d = defer.succeed(name)
            d.addCallback(self._patron.lookup_ns)
            d.addCallback(package_response, name, dns.Record_NS)
            return d

        return defer.fail(failure.Failure(dns.DomainError(query.name)))


class DNSServerFactory(server.DNSServerFactory):

    def handleQuery(self, message, protocol, address):
        '''Copied from twisted.names.
        Adds passing the address to resolver's query method.'''
        query = message.queries[0]
        d = self.resolver.query(query, address)
        d.addCallback(self.gotResolverResponse, protocol, message, address)
        d.addErrback(self.gotResolverError, protocol, message, address)
        return d
