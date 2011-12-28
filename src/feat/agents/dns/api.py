from feat.agents.base import view
from feat.common import serialization, defer, first

from feat.models import model, getter, call, reference, value, action, response
from feat.gateway import models
from feat.utils import locate

from feat.agents.dns.interface import RecordType
from feat.models.interface import ActionCategories


@view.register
@serialization.register
class DnsZones(view.FormatableView):

    name = 'dns_zones'

    def map(doc):
        if doc.get('.type') == 'dns_agent':
            suffix = doc.get('suffix')
            value = dict(agent_id=doc.get('_id'),
                         shard=doc.get('shard'),
                         suffix=suffix)
            yield suffix, value

    view.field('agent_id', None)
    view.field('shard', None)
    view.field('suffix', None)


class Root(model.Model):
    model.identity('api.dns')

    # model.child('zones', model='api.dns.zones', label='Dns zones')
    model.child('entries', model='api.dns.entries', label='Dns entries')


class Zones(model.Collection):
    model.identity('api.dns.zones')


class Entries(model.Collection):
    model.identity('api.dns.entries')

    model.child_names(call.model_call("_get_names"))
    model.child_source(getter.model_get("_locate_agent"))
    model.child_model('api.dns.entries.suffix')

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
        res = reference.Absolute((host, port), "api", "dns", "entries")
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
    action.effect(response.created('Entry created'))

    def create_entry(self, value, prefix, type, entry):
        if type == RecordType.record_A:
            method = self.model.source.add_mapping
        elif type == RecordType.record_CNAME:
            method = self.model.source.add_alias
        else:
            raise ValueError("Unknown record type %r" % (type, ))
        return method(prefix, entry)


class EntrySuffix(model.Collection):
    model.identity('api.dns.entries.suffix')

    model.child_names(call.source_call("get_names"))
    model.child_view(getter.model_get("get_entry"))
    model.child_model('api.dns.entries.suffix.name')

    model.action('post', CreateEntry)

    def get_entry(self, name):
        ret = self.source.get_name_document(name)
        return ret


class DnsName(model.Collection):
    model.identity('api.dns.entries.suffix.name')

    model.child_names(call.model_call('get_names'))
    model.child_view(getter.model_get('get_entry'))
    model.child_model('api.dns.entries.suffix.name.entry')

    def get_names(self):
        return [x.ip for x in self.view.entries]

    def get_entry(self, name):
        entry = first(x for x in self.view.entries if x.ip == name)
        if entry:
            return self.view.name, entry


class DeleteEntry(action.Action):
    action.label('Delete dns entry')
    action.category(ActionCategories.delete)
    action.result(value.Response())
    action.effect(call.action_perform('delete_entry'))
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


class DnsName(model.Model):
    model.identity('api.dns.entries.suffix.name.entry')

    model.attribute('entry', value.String(), getter.model_attr('ip'))
    model.attribute('ttl', value.Integer(), getter.model_attr('ttl'))
    model.attribute('name', value.String(), getter.model_attr('name'))
    model.attribute('type', value.Enum(RecordType), getter.model_attr('type'))

    model.action('delete', DeleteEntry)

    @property
    def ip(self):
        return self.view[1].ip

    @property
    def ttl(self):
        return self.view[1].ttl

    @property
    def name(self):
        return self.view[0]

    @property
    def prefix(self):
        suffix = self.source.get_suffix()
        return self.source._name_to_prefix(self.name, suffix)

    @property
    def type(self):
        return self.view[1].type


models.register_app('dns', Root)
