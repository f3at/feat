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
from twisted.names import server, common, dns, authority
from twisted.python import log
from twisted.internet import reactor, error, defer
from zope.interface import implements, classProvides

from feat.agents.base import replay, labour
from feat.common import time, error as feat_error

from feat.agents.dns.interface import (RecordType, IDNSServerLabourFactory,
                                       IDNSServerLabour)
from feat.agents.application import feat


def get_serial():
    """
    The serial on the zone files is the UNIX epoch time
    """
    return int(time.time())


class Resolver(authority.PySourceAuthority):

    type_name = "dns-resolver"

    def __init__(self, suffix, ns, notify, host_ip, ns_ttl):
        common.ResolverBase.__init__(self)
        self.records = {}
        r_soa = dns.Record_SOA(
                    # This nameserver's name
                    mname = ns,
                    # Mailbox of individual who handles this
                    rname = "root." + suffix,
                    # Unique serial identifying this SOA data
                    serial = get_serial(),
                    # Time interval before zone should be refreshed
                    refresh = str(notify.refresh),
                    # Interval before failed refresh should be retried
                    retry = str(notify.retry),
                    # Upper limit on time interval before expiry
                    expire = str(notify.expire),
                    # Minimum TTL
                    minimum = str(notify.minimum))
        self.soa = (suffix, r_soa)
        self.records.setdefault(suffix, []).append(r_soa)
        self.records.setdefault(suffix, []).append(
            dns.Record_A(address=host_ip))
        self.records.setdefault(suffix, []).append(
            dns.Record_NS(ns, ns_ttl))
        self.cache = {}

    def update_records(self, name, records):
        translated = []
        for record in records:
            factory = dns.Record_A if record.type == RecordType.record_A \
                      else dns.Record_CNAME
            dns_record = factory(record.ip, record.ttl)
            translated.append(dns_record)
        self.records[name] = translated
        if not translated:
            del(self.records[name])

        self._update_serial()

    def _update_serial(self):
        self.soa[1].serial = dns.str2time(get_serial())


@feat.register_restorator
class Labour(labour.BaseLabour):

    classProvides(IDNSServerLabourFactory)
    implements(IDNSServerLabour)

    def __init__(self, patron, notify_cfg, suffix, ip, ns, ns_ttl):
        labour.BaseLabour.__init__(self, patron)
        self._resolver = Resolver(suffix, ns, notify_cfg, ip, ns_ttl)
        self._listener = None
        self._tcp_listener = None
        self._factory = None
        self._slaves = notify_cfg.slaves
        self._suffix = suffix

        self._dns_fact = DNSServerFactory(clients=[self._resolver], verbose=0)
        udp_fact = dns.DNSDatagramProtocol(self._dns_fact)
        self._factory = udp_fact

    ### IDNSServerLabour ###

    @replay.side_effect
    def startup(self, port):
        try:
            self._tcp_listener = reactor.listenTCP(port, self._dns_fact)
        except error.CannotListenError, e:
            feat_error.handle_exception(
                self, e, "Error listening on TCP on port %r", port)
            return False
        try:
            self._listener = reactor.listenUDP(port, self._factory)
        except error.CannotListenError, e:
            feat_error.handle_exception(
                self, e, "Error listening on UDP on port %r", port)
            return False
        return True

    def cleanup(self):
        d = defer.maybeDeferred(self._tcp_listener.stopListening)
        d.addCallback(lambda _: self._listener.stopListening())
        return d

    @replay.side_effect
    def update_records(self, name, records):
        self._resolver.update_records(name, records)

    @replay.side_effect
    def notify_slaves(self):
        self._notify_slaves()

    ### private ###

    def _notify_slaves(self):
        if self._factory and self._factory.transport:
            for ip in self._slaves:
                self._send_notify(ip)

    def _send_notify(self, address):
        msg = dns.Message(opCode=dns.OP_NOTIFY)
        msg.addQuery(self._suffix, type=dns.SOA)
        self.info('Sending notify to %r', address)
        self._factory.writeMessage(msg, address)

    ### used in tests ###

    def get_host(self):
        return self._listener and self._listener.getHost()


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
        """
        Copied from twisted.names.
        Adds passing the address to resolver's query method.
        """
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
