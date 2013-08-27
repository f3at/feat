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
import re

from zope.interface import implements

from feat.agents.base import replay, agent, dependency, contractor, collector
from feat.agents.base import descriptor, cache
from feat.database import view, document
from feat.agents.dns import production, simulation
from feat.agencies import message
from feat.common import fiber, manhole, formatable, text_helper
from feat.agents.application import feat

from feat.agents.dns.interface import (IDNSServerLabourFactory, RecordA,
                                       RecordCNAME, RecordType)
from feat.database.interface import NotFoundError, ResignFromModifying
from feat.interface.agency import ExecMode
from feat.interface.agent import Address
from feat.interface.protocols import InterestType

DEFAULT_PORT = 5553
DEFAULT_AA_TTL = 300
DEFAULT_NS_TTL = 300


@feat.register_restorator
class NotifyConfiguration(formatable.Formatable):

    # SOA zone configuration
    formatable.field('refresh', u'300')
    formatable.field('retry', u'300')
    formatable.field('expire', u'300')
    formatable.field('minimum', u'300')
    # list of slaves bind servers to notify
    formatable.field('slaves', [(u'127.0.0.1', 53)])


@feat.register_restorator
class DNSAgentConfiguration(document.Document):

    type_name = 'dns_agent_conf'
    document.field('doc_id', u'dns_agent_conf', '_id')
    document.field('ns_ttl', DEFAULT_NS_TTL)
    document.field('aa_ttl', DEFAULT_AA_TTL)
    document.field('ns', unicode())
    document.field('suffix', unicode())
    document.field('notify', NotifyConfiguration())


feat.initial_data(DNSAgentConfiguration)


@feat.register_descriptor("dns_agent")
class Descriptor(descriptor.Descriptor):

    descriptor.field('ns', None)
    descriptor.field('ns_ttl', None)
    descriptor.field('aa_ttl', None)
    descriptor.field('suffix', None)
    descriptor.field('notify', None)


@feat.register_restorator
class DnsName(document.Document):

    type_name = 'dns_name'

    # dns zone this name belongs to
    document.field('zone', None, keep_deleted=True)
    # name for which we resolve
    document.field('name', None)
    # list of entries [Entry]
    document.field('entries', list())

    @staticmethod
    def name_to_id(name):
        return unicode("dns_%s" % (name, ))

    @staticmethod
    def id_to_name(doc_id):
        match = re.search('dns_(.*)', doc_id)
        if not match:
            raise AttributeError("doc_id passed: %r is not in recognised "
                                 "format." % (doc_id, ))
        return unicode(match.group(1))


@feat.register_view
class DnsView(view.JavascriptView):

    design_doc_id = 'featjs'
    name = 'dns'

    map = text_helper.format_block('''
    function(doc) {
        if (doc[".type"] == "dns_name") {
            emit(doc["zone"], null);
        }
    }
    ''')

    filter = text_helper.format_block('''
    function(doc, request) {
        var zone;
        if (doc[".type"] == "dns_name") {
            zone = request.query.zone;
            return (!zone || doc.zone == zone);
        }
        return false;
    }
    ''')

    @staticmethod
    def perform_map(doc):
        if doc.get('.type') == 'dns_name':
            zone = doc.get('zone')
            yield zone, None

    @staticmethod
    def perform_filter(doc, request):
        zone = request['query'].get('zone')
        return doc.get('.type') == 'dns_name' and \
               (zone is None or doc.get('zone') == zone)


@feat.register_agent('dns_agent')
class DNSAgent(agent.BaseAgent):

    implements(cache.IDocumentChangeListener)

    categories = {"address": Address.fixed}

    dependency.register(IDNSServerLabourFactory,
                        production.Labour, ExecMode.production)
    dependency.register(IDNSServerLabourFactory,
                        simulation.Labour, ExecMode.test)
    dependency.register(IDNSServerLabourFactory,
                        simulation.Labour, ExecMode.simulation)

    resources = {'dns': 1}

    @replay.mutable
    def initiate(self, state):
        config = state.medium.get_configuration()
        desc = state.medium.get_descriptor()

        state.port = list(desc.resources['dns'].values)[0]
        state.ns_ttl = desc.ns_ttl or config.ns_ttl
        state.aa_ttl = desc.aa_ttl or config.aa_ttl
        state.ns = desc.ns or config.ns or self._lookup_ns()
        state.suffix = desc.suffix or config.suffix or self._lookup_suffix()
        state.notify_cfg = desc.notify or config.notify

        ip = state.medium.get_ip()
        self.debug("Initializing DNS agent with: ip=%r, port=%d, ns_ttl=%d, "
                   "aa_ttl=%d, ns=%s, suffix=%s", ip, state.port, state.ns_ttl,
                   state.aa_ttl, state.ns, state.suffix)

        state.labour = self.dependency(
            IDNSServerLabourFactory, self, state.notify_cfg, state.suffix,
            ip, state.ns, state.ns_ttl)


        ami = state.medium.register_interest(AddMappingContractor)
        rmi = state.medium.register_interest(RemoveMappingContractor)
        muc = state.medium.register_interest(MappingUpdatesCollector)

        ami.bind_to_lobby()
        rmi.bind_to_lobby()
        muc.bind_to_lobby()

        state.cache = cache.DocumentCache(self, self, DnsView,
                                          dict(zone=state.suffix))

        return self._save_configuration_to_descriptor()

    @replay.journaled
    def startup(self, state):
        if not state.labour.startup(state.port):
            raise RuntimeError(
                "Network error: port %d is not available." % state.port)
        self.info("Listening on port %d", state.port)

        f = state.cache.load_view(key=state.suffix)
        f.add_callback(self._load_documents)
        return f

    @replay.journaled
    def on_killed(self, state):
        state.cache.cleanup()
        return fiber.wrap_defer(state.labour.cleanup)

    @replay.journaled
    def shutdown(self, state):
        state.cache.cleanup()
        return fiber.wrap_defer(state.labour.cleanup)

    ### IDocumentChangeListner ###

    @replay.journaled
    def on_document_change(self, state, doc):
        state.labour.update_records(doc.name, doc.entries)
        state.labour.notify_slaves()

    @replay.journaled
    def on_document_deleted(self, state, doc_id):
        name = DnsName.id_to_name(doc_id)
        state.labour.update_records(name, [])
        state.labour.notify_slaves()

    ### end of IDocumentChangeListner ###

    @manhole.expose()
    @replay.mutable
    def add_mapping(self, state, prefix, ip):
        name = self._format_name(prefix, state.suffix)
        record = RecordA(ip=unicode(ip), ttl=state.aa_ttl)
        return self._add_record(name, record)

    @manhole.expose()
    @replay.mutable
    def remove_mapping(self, state, prefix, ip):
        name = self._format_name(prefix, state.suffix)
        record = RecordA(ip=unicode(ip), ttl=state.aa_ttl)
        return self._remove_record(name, record)

    @manhole.expose()
    @replay.mutable
    def add_alias(self, state, prefix, alias):
        name = self._format_name(prefix, state.suffix)
        record = RecordCNAME(ip=unicode(alias), ttl=state.aa_ttl)
        return self._add_record(name, record)

    @manhole.expose()
    @replay.mutable
    def remove_alias(self, state, prefix, alias):
        name = self._format_name(prefix, state.suffix)
        record = RecordCNAME(ip=unicode(alias), ttl=state.aa_ttl)
        return self._remove_record(name, record)

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
        doc_id = DnsName.name_to_id(name)
        try:
            doc = state.cache.get_document(doc_id)
            return doc.entries
        except NotFoundError:
            return []

    ### Used by model ###

    @replay.immutable
    def get_names(self, state):

        resp = [self._name_to_prefix(x[4:], state.suffix)
                for x in state.cache.get_document_ids()]
        return resp

    @replay.immutable
    def get_name_document(self, state, prefix):

        name = self._format_name(prefix, state.suffix)
        doc_id = DnsName.name_to_id(name)
        try:
            doc = state.cache.get_document(doc_id)
            return doc
        except NotFoundError:
            return []

    @replay.immutable
    def get_port(self, state):
        return state.port

    @replay.immutable
    def get_ip(self, state):
        return state.medium.get_ip()

    @replay.immutable
    def get_slaves(self, state):
        return state.notify_cfg.slaves

    ### Private Methods ###

    @replay.mutable
    def _load_documents(self, state, document_ids):
        for doc_id in document_ids:
            doc = state.cache.get_document(doc_id)
            state.labour.update_records(doc.name, doc.entries)
        state.labour.notify_slaves()

    @replay.mutable
    def _add_record(self, state, name, record):
        doc_id = DnsName.name_to_id(name)
        f = self.update_document(doc_id, add_record_body, name, record,
                                 state.suffix)
        f.add_errback(self._create_new_document, name, state.suffix, record)
        return f

    @replay.immutable
    def _create_new_document(self, state, fail, name, suffix, record):
        fail.trap(NotFoundError)
        doc_id = DnsName.name_to_id(name)
        document = DnsName(doc_id=doc_id,
                           name=unicode(name), zone=unicode(suffix),
                           entries=[record])
        return state.medium.save_document(document)

    @replay.mutable
    def _remove_record(self, state, name, record):
        doc_id = DnsName.name_to_id(name)
        f = self.update_document(doc_id, remove_record_body, record)
        f.add_errback(self._trap_not_found)
        return f

    def _trap_not_found(self, fail):
        fail.trap(NotFoundError)

    @replay.side_effect
    def _lookup_ns(self):
        return socket.getfqdn()

    @replay.side_effect
    def _lookup_suffix(self):
        return ".".join(socket.getfqdn().split(".")[1:])

    def _format_name(self, prefix, suffix):
        return unicode(prefix+"."+suffix)

    def _name_to_prefix(self, name, suffix):
        return name[:-(len(suffix) + 1)]

    @agent.update_descriptor
    def _save_configuration_to_descriptor(self, state, desc):
        desc.ns_ttl = state.ns_ttl
        desc.aa_ttl = state.aa_ttl
        desc.ns = state.ns
        desc.suffix = state.suffix
        desc.notify = state.notify_cfg


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
        state.medium.complete(message.FinalReport(payload=payload))

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


def add_record_body(document, name, record, suffix):
    if record in document.entries:
        raise ResignFromModifying()
    if record.type == RecordType.record_CNAME and document.entries:
        document.entries = list()

    document.entries.append(record)
    return document


def remove_record_body(document, record):
    if record not in document.entries:
        raise ResignFromModifying()

    document.entries.remove(record)

    if not document.entries:
        return None
    return document
