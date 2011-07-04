import socket

from twisted.names import server, common, dns, authority
from twisted.python import log
from twisted.internet import reactor, error, defer
from zope.interface import implements, classProvides

from feat.agents.base import replay, labour
from feat.common import serialization

from feat.agents.dns.interface import *


@serialization.register
class Labour(labour.BaseLabour):

    classProvides(IDNSServerLabourFactory)
    implements(IDNSServerLabour)

    def __init__(self, patron, resolver, slaves, suffix):
        labour.BaseLabour.__init__(self, patron)
        self._resolver = resolver
        self._listener = None
        self._tcp_listener = None
        self._factory = None
        self._slaves = slaves
        self._suffix = suffix

    @replay.side_effect
    def initiate(self):
        self._dns_fact = DNSServerFactory(clients=[self._resolver], verbose=0)
        udp_fact = dns.DNSDatagramProtocol(self._dns_fact)
        self._factory = udp_fact

    @replay.side_effect
    def startup(self, port):
        try:
            self._listener = reactor.listenUDP(port, self._factory)
            self._tcp_listener = reactor.listenTCP(port, self._dns_fact)
            return True
        except error.CannotListenError:
            return False

    def cleanup(self):
        d = defer.maybeDeferred(self._tcp_listener.stopListening)
        d.addCallback(lambda _: self._listener.stopListening())
        return d

    def get_host(self):
        return self._listener and self._listener.getHost()

    def get_ip(self):
        return unicode(socket.gethostbyname(socket.gethostname()))

    def notify_slaves(self):
        if self._factory and self._factory.transport:
            for ip in self._slaves:
                self._send_notify(ip)

    def _send_notify(self, address):
        msg = dns.Message(opCode=dns.OP_NOTIFY)
        msg.addQuery(self._suffix, type=dns.SOA)
        self.info('Sending notify to %r', address)
        self._factory.writeMessage(msg, address)


class DNSServerFactory(server.DNSServerFactory):

    def gotResolverError(self, failure, protocol, message, address):
        '''
        Copied from twisted.names.
        Removes logging the whole failure traceback.
        '''
        if failure.check(dns.DomainError, dns.AuthoritativeDomainError):
            message.rCode = dns.ENAME
        else:
            message.rCode = dns.ESERVER
            log.msg(failure.getErrorMessage())

        self.sendReply(protocol, message, address)
        if self.verbose:
            log.msg("Lookup failed")

    def handleQuery(self, message, protocol, address):
        '''
        Copied from twisted.names.
        Adds passing the address to resolver's query method.
        '''
        query = message.queries[0]
        d = self.resolver.query(query, address)
        d.addCallback(self.gotResolverResponse, protocol, message, address)
        d.addErrback(self.gotResolverError, protocol, message, address)
        return d

    def handleNotify(self, message, protocol, address):
        '''
        Not interested in handling notify messages
        '''
        pass
