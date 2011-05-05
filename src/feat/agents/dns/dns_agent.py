# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import socket

from zope.interface import implements

from feat.agents.base import replay, agent, dependency, contractor, collector
from feat.agents.base import descriptor, document, dbtools, message
from feat.agents.dns import production, simulation
from feat.common import fiber, manhole

from feat.agents.dns.interface import *
from feat.interface.agency import *
from feat.interface.agent import *
from feat.interface.protocols import *

DEFAULT_PORT = 5353
DEFAULT_AA_TTL = 300
DEFAULT_NS_TTL = 300


@document.register
class DNSAgentConfiguration(document.Document):

    document_type = 'dns_agent_conf'
    document.field('doc_id', u'dns_agent_conf', '_id', unicode)
    document.field('port', DEFAULT_PORT)
    document.field('ns_ttl', DEFAULT_NS_TTL)
    document.field('aa_ttl', DEFAULT_AA_TTL)
    document.field('ns', None)
    document.field('suffix', None)


dbtools.initial_data(DNSAgentConfiguration)


@descriptor.register("dns_agent")
class Descriptor(descriptor.Descriptor):
    pass


@agent.register('dns_agent')
class DNSAgent(agent.BaseAgent):

    implements(IDNSServerPatron)

    categories = {"address": Address.fixed}

    dependency.register(IDNSServerLabourFactory,
                        production.Labour, ExecMode.production)
    dependency.register(IDNSServerLabourFactory,
                        simulation.Labour, ExecMode.test)
    dependency.register(IDNSServerLabourFactory,
                        simulation.Labour, ExecMode.simulation)

    @replay.mutable
    def initiate(self, state, port=None, ns_ttl=None, aa_ttl=None,
                 ns=None, suffix=None):
        agent.BaseAgent.initiate(self)

        config = state.medium.get_configuration()

        state.port = port or config.port
        state.ns_ttl = ns_ttl or config.ns_ttl
        state.aa_ttl = aa_ttl or config.aa_ttl
        state.ns = ns or config.ns or self._lookup_ns()
        state.suffix = suffix or config.suffix or self._lookup_suffix()

        self.debug("Initializing DNS agent with: port=%d, ns_ttl=%d, "
                   "aa_ttl=%d, ns=%s, suffix=%s", state.port, state.ns_ttl,
                   state.aa_ttl, state.ns, state.suffix)

        state.mapping = {} # {PREFIX: [IPs]}
        state.labour = self.dependency(IDNSServerLabourFactory, self)

        ami = state.medium.register_interest(AddMappingContractor)
        rmi = state.medium.register_interest(RemoveMappingContractor)
        muc = state.medium.register_interest(MappingUpdatesCollector)

        ami.bind_to_lobby()
        rmi.bind_to_lobby()
        muc.bind_to_lobby()

        f = fiber.succeed()
        f.add_callback(fiber.drop_result, state.labour.initiate)
        f.add_callback(fiber.drop_result, self.initiate_partners)
        return f

    @replay.journaled
    def startup(self, state):
        agent.BaseAgent.startup(self)
        if state.labour.startup(state.port):
            self.info("Listening on UDP port %d", state.port)
            return
        self.error("Network error: UDP port %d is not available." % state.port)
        #FIXME: should retry or shutdown the agent

    @manhole.expose()
    @replay.mutable
    def add_mapping(self, state, prefix, ip):
        ips = state.mapping.get(prefix)
        if ips is None:
            ips = []
            state.mapping[prefix] = ips
        if ip in ips:
            self.log("Keeping DNS mapping from %s to %s", prefix, ip)
            return False
        state.mapping[prefix].append(ip)
        self.debug("Adding DNS mapping from %s to %s added", prefix, ip)
        return True

    @manhole.expose()
    @replay.mutable
    def remove_mapping(self, state, prefix, ip):
        if prefix not in state.mapping:
            self.log("Unknown DNS mapping prefix %s", prefix)
            return False
        try:
            ips = state.mapping[prefix]
            ips.remove(ip)
            if not ips:
                del state.mapping[prefix]
            self.debug("Removing DNS mapping from %s to %s", prefix, ip)
            return True
        except ValueError:
            self.log("Unknown DNS mapping IP %s", ip)
            return False

    ### IDNSServerPatron Methods ###

    @manhole.expose()
    @replay.mutable
    def lookup_address(self, state, name, _address):
        full_suffix = "." + state.suffix
        if name.endswith(full_suffix):
            prefix = name[:-len(full_suffix)]
            if prefix in state.mapping:
                ips = state.mapping[prefix]
                if ips:
                    # Performing round robin
                    ips = state.mapping[prefix]
                    first = ips.pop(0)
                    ips.append(first)

                    self.debug("Resolved A query for %s to %s (TTL %d)",
                               name, ", ". join(ips), state.ns_ttl)
                    return [(ip, state.aa_ttl) for ip in ips]

        self.debug("Failed to resolve A query for %s", name)
        return []

    @replay.immutable
    def get_suffix(self, state):
        return state.suffix

    @manhole.expose()
    @replay.mutable
    def lookup_ns(self, state, name):
        self.debug("Resolved NS query for %s to %s (TTL %d)",
                   name, state.ns, state.ns_ttl)
        return state.ns, state.ns_ttl

    ### Private Methods ###

    def _lookup_ns(self):
        return socket.getfqdn()

    def _lookup_suffix(self):
        return ".".join(socket.getfqdn().split(".")[1:])


class DNSMappingContractor(contractor.BaseContractor):

    interest_type = InterestType.public

    @replay.immutable
    def announced(self, state, announcement):
        state.medium.bid(message.Bid())

    @replay.immutable
    def granted(self, state, grant):
        prefix = grant.payload['prefix']
        ip = grant.payload['ip']
        self.tell_agent(prefix, ip)
        payload = dict(suffix=state.agent.get_suffix())
        state.medium.finalize(message.FinalReport(payload=payload))

    def tell_agent(self, prefix, ip):
        """To be overriden in sub-classes."""


class AddMappingContractor(DNSMappingContractor):

    protocol_id = 'add-dns-mapping'

    @replay.immutable
    def tell_agent(self, state, prefix, ip):
        state.agent.add_mapping(prefix, ip)


class RemoveMappingContractor(DNSMappingContractor):

    protocol_id = 'remove-dns-mapping'

    @replay.immutable
    def tell_agent(self, state, prefix, ip):
        state.agent.remove_mapping(prefix, ip)


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
