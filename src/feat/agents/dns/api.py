import socket

from feat.database import view
from feat.agents.common import start_agent
from feat.common import defer, first

from feat.models import model, getter, call, reference, value, action, response
from feat.gateway import models
from feat.utils import locate

from feat.agents.dns.interface import RecordType
from feat.agents.dns import dns_agent
from feat.models.interface import ActionCategories
from feat.interface.recipient import IRecipient
from feat.agents.application import feat


@feat.register_view
@feat.register_restorator
class DnsZones(view.FormatableView):

    name = 'dns_zones'

    def map(doc):
        if doc.get('.type') == 'dns_agent':
            suffix = doc.get('suffix')
            # extract port
            r = doc.get('resources')
            r = r and r.get('dns')
            r = r and r.get('values')
            port = r and r[1]

            value = dict(agent_id=doc.get('_id'),
                         shard=doc.get('shard'),
                         port=port,
                         suffix=suffix)

            yield suffix, value

    view.field('agent_id', None)
    view.field('shard', None)
    view.field('suffix', None)
    view.field('port', None)


@feat.register_model
class Root(model.Model):
    model.identity('apps.dns')

    model.child('servers', model='apps.dns.servers', label='Dns servers',
                desc='List of servers running.')
    model.child('entries', model='apps.dns.entries', label='Dns entries')


class SlavesValue(value.String):

    def validate(self, value):
        """
        Accepts: str, unicode
        Returns: list of tuples in the format (ip, port)
        """
        val = super(SlavesValue, self).validate(value)

        slaves = val.replace(" ", "")
        slaves = filter(None, slaves.split(','))
        slaves = [x.split(":") for x in slaves]
        res = list()
        for x in slaves:
            self._validate_ip(x[0])
            if len(x) == 1:
                res.append((x[0], 53))
            else:
                res.append((x[0], int(x[1])))
        return res

    def publish(self, value):
        """
        Accepts: list of tuples in the format (ip, port)
        Returns: unicode
        """
        if not isinstance(value, list):
            raise ValueError(value)
        slaves = ['%s:%d' % x for x in value]
        return unicode(", ".join(slaves))

    def _validate_ip(self, ip):
        try:
            socket.inet_aton(ip)
        except socket.error:
            raise ValueError("%s is not a valid ip address" % (ip, ))


class SpawnServer(action.Action):
    action.label('Start new server')
    action.param('suffix', value.String())
    action.param('slaves', SlavesValue(),
                 desc=("Slaves to push zone updates. Format: "
                       "'ip:port, ip:port'"),
                 is_required=False)
    action.param('ns', value.String(), desc="The nameservers name",
                 is_required=False)
    action.param('refresh', value.Integer(300),
                 desc="Number of seconds the zone should be refreshed",
                 is_required=False)
    action.param('retry', value.Integer(300),
                 desc="Interval before failed refresh should be retried",
                 is_required=False)
    action.param('expire', value.Integer(300),
                 desc="Upper limit on time interval before expiry",
                 is_required=False)
    action.param('minimum', value.Integer(300),
                 desc="Minimum TTL",
                 is_required=False)
    action.result(value.Response())
    action.effect(call.action_perform('spawn_agent'))
    action.effect(call.action_filter('render_reference'))
    action.effect(response.created('Server spawned'))

    def spawn_agent(self, suffix, slaves=None, ns=None, refresh=None,
                    retry=None, expire=None, minimum=None):
        notify = dns_agent.NotifyConfiguration(
            slaves=slaves, refresh=refresh,
            expire=expire, minimum=minimum, retry=retry)
        desc = dns_agent.Descriptor(ns=ns, notify=notify, suffix=suffix)
        d = self.model.source.host_agent_call(
            'initiate_protocol', start_agent.GloballyStartAgent, desc)
        d.addCallback(defer.call_param, 'notify_finish')
        return d

    def render_reference(self, value):
        if IRecipient.providedBy(value):
            return reference.Relative('servers', value.key)


@feat.register_model
class Servers(model.Collection):
    model.identity('apps.dns.servers')

    model.child_names(call.model_call("get_names"))
    model.child_source(getter.model_get("locate_agent"))
    model.child_model('apps.dns.servers.id')

    model.action('post', SpawnServer)

    def db(self):
        if not hasattr(self, '_db'):
            self._db = self.source._database.get_connection()
        return self._db

    def get_names(self):

        def unpack(result):
            return [x.agent_id for x in result]

        db = self.db()
        d = db.query_view(DnsZones)
        d.addCallback(unpack)
        return d

    @defer.inlineCallbacks
    def locate_agent(self, agent_id):
        db = self.db()
        agency = self.source

        medium = agency.get_agent(agent_id)
        if medium is not None:
            defer.returnValue(medium.get_agent())

        host = yield locate.locate(db, agent_id)

        if host is None:
            return
        port = self.source.config['gateway']['port']
        res = reference.Absolute((host, port), "apps", "dns", "servers",
                                 agent_id)
        defer.returnValue(res)


@feat.register_model
class Server(model.Model):
    model.identity('apps.dns.servers.id')
    model.attribute('port', value.Integer(), call.source_call('get_port'))
    model.attribute('ip', value.String(), call.source_call('get_ip'))
    model.attribute('suffix', value.String(), call.source_call('get_suffix'))
    model.attribute('slaves', SlavesValue(), call.source_call('get_slaves'))

    model.delete("del",
                 call.source_call("terminate"),
                 call.model_call("render_reference"),
                 response.deleted("Agent terminated"),
                 label="Terminate", desc="Terminate the server")

    def render_reference(self):
        return reference.Local('apps', 'dns', 'servers')


@feat.register_model
class Entries(model.Collection):
    model.identity('apps.dns.entries')

    model.child_names(call.model_call("_get_names"))
    model.child_source(getter.model_get("_locate_agent"))
    model.child_model('apps.dns.entries.suffix')

    def db(self):
        if not hasattr(self, '_db'):
            self._db = self.source._database.get_connection()
        return self._db

    def _get_names(self):

        def unpack(result):
            return [x.suffix for x in result]

        db = self.db()
        d = db.query_view(DnsZones)
        d.addCallback(unpack)
        return d

    @defer.inlineCallbacks
    def _locate_agent(self, name):
        db = self.db()
        view = yield db.query_view(DnsZones, key=name)
        if not view:
            return
        agent_id = view[0].agent_id

        agency = self.source

        medium = agency.get_agent(agent_id)
        if medium is not None:
            defer.returnValue(medium.get_agent())

        host = yield locate.locate(db, agent_id)

        if host is None:
            return
        port = self.source.config['gateway']['port']
        res = reference.Absolute((host, port), "apps", "dns", "entries")
        defer.returnValue(res)


class CreateEntry(action.Action):
    action.label('Create dns entry')
    action.param('prefix', value.String(),
                 label='Prefix')
    action.param('type', value.Enum(RecordType),
                 label='Entry type')
    action.param('entry', value.String(),
                 label='Entry', desc='IP or name to alias')
    action.category(ActionCategories.create)
    action.result(value.Response())
    action.effect(call.action_perform('create_entry'))
    action.effect(call.action_call('render_reference'))
    action.effect(response.created('Entry created'))

    def create_entry(self, value, prefix, type, entry):
        if type == RecordType.record_A:
            method = self.model.source.add_mapping
        elif type == RecordType.record_CNAME:
            method = self.model.source.add_alias
        else:
            raise ValueError("Unknown record type %r" % (type, ))
        return method(prefix, entry)

    def render_reference(self):
        return reference.Relative(self.model.source.get_suffix())


@feat.register_model
class EntrySuffix(model.Collection):
    model.identity('apps.dns.entries.suffix')

    model.child_names(call.source_call("get_names"))
    model.child_view(getter.model_get("get_entry"))
    model.child_model('apps.dns.entries.suffix.name')
    model.meta("html-render", "array, 2")

    model.action('post', CreateEntry)

    def get_entry(self, name):
        ret = self.source.get_name_document(name)
        return ret


@feat.register_model
class DnsName(model.Collection):
    model.identity('apps.dns.entries.suffix.name')

    model.child_names(call.model_call('get_names'))
    model.child_view(getter.model_get('get_entry'))
    model.child_model('apps.dns.entries.suffix.name.entry')

    def get_names(self):
        return [x.ip for x in self.view.entries]

    def get_entry(self, name):
        entry = first(x for x in self.view.entries if x.ip == name)
        if entry:
            return self.view.name, entry


class DeleteEntry(action.Action):
    action.label('Delete dns entry')
    action.category(ActionCategories.delete)
    action.is_idempotent()
    action.result(value.Response())
    action.effect(call.action_perform('delete_entry'))
    action.effect(call.action_call('render_reference'))
    action.effect(response.deleted('Entry deleted'))

    def delete_entry(self):
        prefix = self.model.prefix
        entry = self.model.ip
        if self.model.type == RecordType.record_A:
            method = self.model.source.remove_mapping
        elif self.model.type == RecordType.record_CNAME:
            method = self.model.source.remove_alias
        else:
            raise ValueError("Unknown record type %r" % (type, ))
        return method(prefix, entry)

    def render_reference(self):
        suffix = self.model.source.get_suffix()
        return reference.Local('apps', 'dns', 'entries', suffix)


@feat.register_model
class DnsName(model.Model):
    model.identity('apps.dns.entries.suffix.name.entry')

    model.attribute('entry', value.String(), getter.model_attr('ip'))
    model.attribute('ttl', value.Integer(), getter.model_attr('ttl'))
    model.attribute('name', value.String(), call.model_call('get_name'))
    model.attribute('type', value.Enum(RecordType), getter.model_attr('type'))

    model.action('del', DeleteEntry)
    model.item_meta('entry', "html-link", "owner")

    @property
    def ip(self):
        return self.view[1].ip

    @property
    def ttl(self):
        return self.view[1].ttl

    def get_name(self):
        return self.view[0]

    @property
    def prefix(self):
        suffix = self.source.get_suffix()
        return self.source._name_to_prefix(self.get_name(), suffix)

    @property
    def type(self):
        return self.view[1].type


models.register_app('dns', Root)
