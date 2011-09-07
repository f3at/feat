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
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import socket
import time

from zope.interface import implements
from twisted.names import common, dns, authority

from feat.agents.base import replay, agent, dependency, contractor, collector
from feat.agents.base import descriptor, document, dbtools, message
from feat.agents.common import export
from feat.agents.dns import production, simulation
from feat.common import fiber, manhole, formatable, serialization

from feat.agents.dns.interface import IDNSServerLabourFactory
from feat.interface.serialization import ISerializable
from feat.interface.agency import ExecMode
from feat.interface.agent import Address
from feat.interface.protocols import InterestType

DEFAULT_PORT = 5553
DEFAULT_AA_TTL = 300
DEFAULT_NS_TTL = 300


def get_serial():
    """
    The serial on the zone files is the UNIX epoch time
    """
    return int(time.time())


@serialization.register
class NotifyConfiguration(formatable.Formatable):

    # SOA zone configuration
    formatable.field('refresh', u'300')
    formatable.field('retry', u'300')
    formatable.field('expire', u'300')
    formatable.field('minimum', u'300')
    # list of slaves bind servers to notify
    formatable.field('slaves', [(u'127.0.0.1', 53)])


@document.register
class DNSAgentConfiguration(document.Document):

    document_type = 'dns_agent_conf'
    document.field('doc_id', u'dns_agent_conf', '_id')
    document.field('port', DEFAULT_PORT)
    document.field('ns_ttl', DEFAULT_NS_TTL)
    document.field('aa_ttl', DEFAULT_AA_TTL)
    document.field('ns', unicode())
    document.field('suffix', unicode())
    document.field('notify', NotifyConfiguration())


dbtools.initial_data(DNSAgentConfiguration)


@descriptor.register("dns_agent")
class Descriptor(descriptor.Descriptor):
    pass


@agent.register('dns_agent')
class DNSAgent(agent.BaseAgent):

    categories = {"address": Address.fixed}

    dependency.register(IDNSServerLabourFactory,
                        production.Labour, ExecMode.production)
    dependency.register(IDNSServerLabourFactory,
                        simulation.Labour, ExecMode.test)
    dependency.register(IDNSServerLabourFactory,
                        simulation.Labour, ExecMode.simulation)

    migratability = export.Migratability.not_migratable

    @replay.mutable
    def initiate(self, state, port=None, ns_ttl=None, aa_ttl=None,
                 ns=None, suffix=None):
        config = state.medium.get_configuration()

        state.port = port or config.port
        state.ns_ttl = ns_ttl or config.ns_ttl
        state.aa_ttl = aa_ttl or config.aa_ttl
        state.ns = ns or config.ns or self._lookup_ns()
        state.suffix = suffix or config.suffix or self._lookup_suffix()
        state.notify_cfg = config.notify

        self.debug("Initializing DNS agent with: port=%d, ns_ttl=%d, "
                   "aa_ttl=%d, ns=%s, suffix=%s", state.port, state.ns_ttl,
                   state.aa_ttl, state.ns, state.suffix)

        state.resolver = Resolver(state.suffix, state.ns, state.notify_cfg,
                                  self._get_ip(), state.ns_ttl)

        state.labour = self.dependency(IDNSServerLabourFactory,
                                       self, state.resolver,
                                       state.notify_cfg.slaves,
                                       state.suffix)

        ami = state.medium.register_interest(AddMappingContractor)
        rmi = state.medium.register_interest(RemoveMappingContractor)
        muc = state.medium.register_interest(MappingUpdatesCollector)

        ami.bind_to_lobby()
        rmi.bind_to_lobby()
        muc.bind_to_lobby()

        f = fiber.succeed()
        f.add_callback(fiber.drop_param, state.labour.initiate)
        return f

    @replay.journaled
    def startup(self, state):
        self.startup_monitoring()
        if state.labour.startup(state.port):
            self.info("Listening on port %d", state.port)
            return
        self.error("Network error: port %d is not available." % state.port)
        #FIXME: should retry or shutdown the agent

    @replay.journaled
    def on_killed(self, state):
        return fiber.wrap_defer(state.labour.cleanup)

    @replay.journaled
    def shutdown(self, state):
        return fiber.wrap_defer(state.labour.cleanup)

    @manhole.expose()
    @replay.mutable
    def add_mapping(self, state, prefix, ip):
        self.log(state.resolver.records)
        record = dns.Record_A(ip, state.aa_ttl)
        name = state.resolver.format_name(prefix, state.suffix)
        if not state.resolver.add_record(name, record):
            self.log("Keeping DNS mapping from %s to %s", prefix, ip)
            return False
        state.labour.notify_slaves()
        self.debug("DNS mapping from %s to %s added", prefix, ip)
        return True

    @manhole.expose()
    @replay.mutable
    def remove_mapping(self, state, prefix, ip):
        record = dns.Record_A(ip, state.aa_ttl)
        name = state.resolver.format_name(prefix, state.suffix)
        if not state.resolver.remove_record(name, record):
            self.log("Unknown DNS mapping prefix %s %s", prefix, ip)
            return False
        self.debug("Removing DNS mapping from %s to %s", prefix, ip)
        state.labour.notify_slaves()
        return True

    @manhole.expose()
    @replay.mutable
    def add_alias(self, state, prefix, alias):
        self.log(state.resolver.records)
        name = state.resolver.format_name(prefix, state.suffix)
        record = dns.Record_CNAME(name, state.aa_ttl)
        if not state.resolver.add_record(alias, record):
            self.log("Keeping DNS alias from %s to %s", prefix, alias)
            return False
        state.labour.notify_slaves()
        self.debug("DNS alias from %s to %s added", prefix, alias)
        return True

    @manhole.expose()
    @replay.mutable
    def remove_alias(self, state, prefix, alias):
        name = state.resolver.format_name(prefix, state.suffix)
        record = dns.Record_CNAME(name, state.aa_ttl)
        if not state.resolver.remove_record(alias, record):
            self.log("Unknown DNS alias prefix %s %s", prefix, alias)
            return False
        self.debug("Removing DNS alias from %s to %s", prefix, alias)
        state.labour.notify_slaves()
        return True

    @manhole.expose()
    @replay.mutable
    def lookup_address(self, state, name, _address):
        records = state.resolver.get_records(name)
        records = filter(lambda r: r.TYPE == dns.A, records)
        if not records:
            self.debug("Failed to resolve A query for %s", name)
            return []
        ips = [(r.dottedQuad(), r.ttl) for r in records]
        self.debug("Resolved A query for %s (TTL %d)",
                               name, state.ns_ttl)
        return ips

    @manhole.expose()
    @replay.mutable
    def lookup_alias(self, state, name):
        records = state.resolver.get_records(name)
        records = filter(lambda r: r.TYPE == dns.CNAME, records)
        if not records:
            self.debug("Failed to resolve CNAME query for %s", name)
            return None, None
        alias = (str(records[0].name), records[0].ttl)
        self.debug("Resolved CNAME query for %s (TTL %d)",
                               name, state.ns_ttl)
        return alias

    @manhole.expose()
    @replay.mutable
    def lookup_ns(self, state, name):
        self.debug("Resolved NS query for %s to %s (TTL %d)",
                   name, state.ns, state.ns_ttl)
        return state.ns, state.ns_ttl

    @replay.immutable
    def get_suffix(self, state):
        return state.suffix

    ### Private Methods ###

    def _lookup_ns(self):
        return socket.getfqdn()

    def _lookup_suffix(self):
        return ".".join(socket.getfqdn().split(".")[1:])

    @replay.side_effect
    def _get_ip(self):
        return unicode(socket.gethostbyname(socket.gethostname()))


class Resolver(authority.PySourceAuthority):

    implements(ISerializable)

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

    def add_record(self, name, record):
        records = self.records.get(name, [])
        if record in records:
            return False
        if record.TYPE == dns.CNAME and records:
            return False
        self.records.setdefault(name, []).append(record)
        self._update_serial()
        return True

    def remove_record(self, name, record):
        records = self.records.get(name, [])
        if record not in records:
            return False
        records.remove(record)
        if not records:
            self.records.pop(name, None)
        self._update_serial()
        return True

    def get_records(self, name):
        return self.records.get(name, [])

    def format_name(self, prefix, suffix):
        return prefix+"."+suffix

    def _update_serial(self):
        self.soa[1].serial = dns.str2time(get_serial())

    ### ISerializable Methods ###

    def snapshot(self):
        return dict()

    def __eq__(self, other):
        if not isinstance(other, Resolver):
            return NotImplemented
        return True

    def __ne__(self, other):
        if not isinstance(other, Resolver):
            return NotImplemented
        return False


class DNSMappingContractor(contractor.BaseContractor):

    interest_type = InterestType.public

    @replay.immutable
    def announced(self, state, announcement):
        state.medium.bid(message.Bid())

    @replay.immutable
    def granted(self, state, grant):
        prefix = grant.payload['prefix']
        mtype = grant.payload['mtype']
        mapping = grant.payload['mapping']
        self.tell_agent(mtype, prefix, mapping)
        payload = dict(suffix=state.agent.get_suffix())
        state.medium.finalize(message.FinalReport(payload=payload))

    def tell_agent(self, prefix, ip):
        """To be overriden in sub-classes."""


class AddMappingContractor(DNSMappingContractor):

    protocol_id = 'add-dns-mapping'

    @replay.immutable
    def tell_agent(self, state, mtype, prefix, mapping):
        if mtype == dns.A:
            state.agent.add_mapping(prefix, mapping)
        elif mtype == dns.CNAME:
            state.agent.add_alias(prefix, mapping)


class RemoveMappingContractor(DNSMappingContractor):

    protocol_id = 'remove-dns-mapping'

    @replay.immutable
    def tell_agent(self, state, mtype, prefix, mapping):
        if mtype == dns.A:
            state.agent.remove_mapping(prefix, mapping)
        elif mtype == dns.CNAME:
            state.agent.remove_alias(prefix, mapping)


class MappingUpdatesCollector(collector.BaseCollector):

    protocol_id = 'update-dns-mapping'
    interest_type = InterestType.public

    def notified(self, msg):
        action, args = msg.payload
        handler = getattr(self, "action_" + action, None)
        if not handler:
            self.warning("Unknown mapping update action: %s", action)
            return
        return handler(*args)

    @replay.immutable
    def action_add_mapping(self, state, prefix, ip):
        state.agent.add_mapping(prefix, ip)

    @replay.immutable
    def action_remove_mapping(self, state, prefix, ip):
        state.agent.remove_mapping(prefix, ip)

    @replay.immutable
    def action_add_alias(self, state, prefix, alias):
        state.agent.add_alias(prefix, alias)

    @replay.immutable
    def action_remove_alias(self, state, prefix, alias):
        state.agent.remove_alias(prefix, alias)
