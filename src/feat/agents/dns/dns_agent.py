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

from feat.agents.base import replay, agent, dependency, contractor, collector
from feat.agents.base import descriptor, document, dbtools, message
from feat.agents.common import export
from feat.agents.dns import production, simulation
from feat.common import fiber, manhole, formatable, serialization

from feat.agents.dns.interface import (IDNSServerLabourFactory, Record,
                                       RecordType)
from feat.interface.agency import ExecMode
from feat.interface.agent import Address
from feat.interface.protocols import InterestType

DEFAULT_PORT = 5553
DEFAULT_AA_TTL = 300
DEFAULT_NS_TTL = 300


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

        state.records = dict()

        state.port = port or config.port
        state.ns_ttl = ns_ttl or config.ns_ttl
        state.aa_ttl = aa_ttl or config.aa_ttl
        state.ns = ns or config.ns or self._lookup_ns()
        state.suffix = suffix or config.suffix or self._lookup_suffix()
        state.notify_cfg = config.notify

        self.debug("Initializing DNS agent with: port=%d, ns_ttl=%d, "
                   "aa_ttl=%d, ns=%s, suffix=%s", state.port, state.ns_ttl,
                   state.aa_ttl, state.ns, state.suffix)

        ip = state.medium.get_ip()
        state.labour = self.dependency(
            IDNSServerLabourFactory, self, state.notify_cfg, state.suffix,
            ip, state.ns, state.ns_ttl)


        ami = state.medium.register_interest(AddMappingContractor)
        rmi = state.medium.register_interest(RemoveMappingContractor)
        muc = state.medium.register_interest(MappingUpdatesCollector)

        ami.bind_to_lobby()
        rmi.bind_to_lobby()
        muc.bind_to_lobby()

    @replay.journaled
    def startup(self, state):
        self.startup_monitoring()
        if not state.labour.startup(state.port):
            raise RuntimeError(
                "Network error: port %d is not available." % state.port)
        self.info("Listening on port %d", state.port)

    @replay.journaled
    def on_killed(self, state):
        return fiber.wrap_defer(state.labour.cleanup)

    @replay.journaled
    def shutdown(self, state):
        return fiber.wrap_defer(state.labour.cleanup)

    @manhole.expose()
    @replay.mutable
    def add_mapping(self, state, prefix, ip):
        name = self._format_name(prefix, state.suffix)
        record = Record(name=name, ip=ip, ttl=state.aa_ttl,
                        type=RecordType.record_A)
        if not self._add_record(record):
            return False
        state.labour.update_records(name, self.get_records(name))
        return True

    @manhole.expose()
    @replay.mutable
    def remove_mapping(self, state, prefix, ip):
        name = self._format_name(prefix, state.suffix)
        record = Record(name=name, ip=ip, ttl=state.aa_ttl,
                        type=RecordType.record_A)
        if not self._remove_record(record):
            self.log("Unknown DNS mapping prefix %s %s", record.name, ip)
            return False
        self.debug("Removing DNS mapping from %s to %s", record.name, ip)
        state.labour.update_records(name, self.get_records(name))
        return True

    @manhole.expose()
    @replay.mutable
    def add_alias(self, state, prefix, alias):
        name = self._format_name(prefix, state.suffix)
        record = Record(name=alias, ip=name, ttl=state.aa_ttl,
                        type=RecordType.record_CNAME)
        if not self._add_record(record):
            self.log("Keeping DNS alias from %s to %s", name, alias)
            return False
        state.labour.update_records(name, self.get_records(name))
        return True

    @manhole.expose()
    @replay.mutable
    def remove_alias(self, state, prefix, alias):
        name = self._format_name(prefix, state.suffix)
        record = Record(name=alias, ip=name, ttl=state.aa_ttl,
                        type=RecordType.record_CNAME)
        if not self._remove_record(record):
            self.log("Unknown DNS alias prefix %s %s", name, alias)
            return False
        state.labour.update_records(name, self.get_records(name))
        return True

    @manhole.expose()
    @replay.immutable
    def lookup_address(self, state, name, _address):
        records = [r for r in self.get_records(name)
                   if r.type == RecordType.record_A]
        if not records:
            self.debug("Failed to resolve A query for %s", name)
            return []
        ips = [(r.ip, r.ttl) for r in records]
        self.debug("Resolved A query for %s (TTL %d)", name, state.ns_ttl)
        return ips

    @manhole.expose()
    @replay.immutable
    def lookup_alias(self, state, name):
        records = [r for r in self.get_records(name)
                   if r.type == RecordType.record_CNAME]
        if not records:
            self.debug("Failed to resolve CNAME query for %s", name)
            return None, None
        alias = (str(records[0].ip), records[0].ttl)
        self.debug("Resolved CNAME query for %s (TTL %d)", name, state.ns_ttl)
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

    @replay.immutable
    def get_records(self, state, name):
        return state.records.get(name, [])

    ### Private Methods ###

    @replay.mutable
    def _add_record(self, state, record):
        records = state.records.get(record.name, [])
        if record in records:
            return False
        if record.type == RecordType.record_CNAME and records:
            return False
        records.append(record)
        self.debug("DNS mapping type: %s from %s to %s added", record.type,
                   record.name, record.ip)
        state.records[record.name] = records
        return True

    @replay.mutable
    def _remove_record(self, state, record):
        records = state.records.get(record.name, [])
        if record not in records:
            return False
        records.remove(record)
        if not records:
            state.records.pop(record.name, None)
        return True

    def _lookup_ns(self):
        return socket.getfqdn()

    def _lookup_suffix(self):
        return ".".join(socket.getfqdn().split(".")[1:])

    def _format_name(self, prefix, suffix):
        return prefix+"."+suffix


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
        if mtype == RecordType.record_A:
            state.agent.add_mapping(prefix, mapping)
        elif mtype == RecordType.record_CNAME:
            state.agent.add_alias(prefix, mapping)


class RemoveMappingContractor(DNSMappingContractor):

    protocol_id = 'remove-dns-mapping'

    @replay.immutable
    def tell_agent(self, state, mtype, prefix, mapping):
        if mtype == RecordType.record_A:
            state.agent.remove_mapping(prefix, mapping)
        elif mtype == RecordType.record_CNAME:
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
