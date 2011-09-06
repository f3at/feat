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
from pprint import pformat

from feat.agencies import tunneling
from feat.agents.base import (agent, replay, recipient, task, descriptor,
                              alert, notifier, )
from feat.agents.common import start_agent
from feat.common import (fiber, serialization, formatable, manhole,
                         error, text_helper, )
from feat.agents.migration import protocol, spec


@agent.register('migration_agent')
class MigrationAgent(agent.BaseAgent, alert.AgentMixin, notifier.AgentMixin):

    @replay.mutable
    def initiate(self, state):
        state.medium.register_interest(protocol.Replier)
        state.medium.enable_channel('tunnel')
        state.exports = ExportAgents()

        self._set_semaphore(False)

    @replay.mutable
    def startup(self, state):
        return self.discover_local()

    @manhole.expose()
    @replay.journaled
    def discover_local(self, state):
        '''discover_local() -> Called at startup to discover export agent
        running in this cluser.'''
        f = self.discover_service(protocol.Requester, timeout=1, shard='lobby')
        f.add_callback(self._got_local)
        return f

    @manhole.expose()
    @replay.mutable
    def set_current(self, state, name):
        '''set_current(name) -> instructs migration agent to speak by default
        with the named export agent.'''
        return state.exports.set_current(name)

    @manhole.expose()
    @replay.journaled
    def get_structure(self, state, export=None):
        '''get_structure(export=current) -> query shard structure in the other
        cluster and returns the result which can be formated with
        show_structure().'''

        def parse(response):
            return response.shards

        tunel = state.exports.get_by_name(export)
        req = self.initiate_protocol(protocol.Requester, tunel.recipient,
                                     spec.GetShardStructure())
        f = req.notify_finish()
        f.add_callback(parse)
        return f

    @manhole.expose()
    def show_structure(self, shards):
        '''show_structure(shards) -> display in a nice way result of the query
        shards view.'''
        return self._render_shard_table(shards)

    @manhole.expose()
    @replay.immutable
    def show_exports(self, state):
        '''show_exports() -> show currently known export agents.'''
        resp = []
        c = state.exports.get_current()
        if c:
            resp += ["Current tunnel: %s" % c.name]
        t = text_helper.Table(fields=("Name", "Version", ),
                              lengths=(30, 20, ))
        resp += [t.render((x.name, x.version, )
                          for x in state.exports.iter_entries())]
        return "\n".join(resp)

    @manhole.expose()
    @replay.journaled
    def handshake(self, state, recp):

        def parse(response):
            return AgentEntry(recipient=recp,
                              name=response.name,
                              version=response.version)

        if isinstance(recp, (str, unicode)):
            recp = tunneling.parse(recp)

        req = self.initiate_protocol(
            protocol.Requester, recp, spec.Handshake())
        f = req.notify_finish()
        f.add_callback(parse)
        f.add_callback(self._add_export_entry)
        return f

    @manhole.expose()
    @replay.journaled
    def prepare_shard_migration(self, state, shard, export=None):
        '''prepare_shard_mgiration(shard, export=current) -> creates migration
        object representing full shutdown of the shard.'''

        def evalute(migration, list_so_far):
            if migration.completable:
                list_so_far.append(migration.ident)
            return list_so_far

        if not isinstance(shard, spec.ShardStructure):
            raise TypeError(
                "Expected argument 1 to be ShardStructure, got %r" % shard)

        migratable = list()
        f = fiber.succeed()
        for host in shard.hosts:
            recp = recipient.Agent(host, shard.shard)
            f.add_callback(fiber.drop_param, self.prepare_host_migration,
                           recp, export)
            f.add_callback(evalute, migratable)
        f.add_callback(self.join_migrations, export)
        return f

    @manhole.expose()
    @replay.journaled
    def prepare_host_migration(self, state, recp, export=None):
        '''prepare_host_migration(self, recp, export=current) -> creates
        migration object representing full shutdown of the host with recp.'''
        recp = recipient.IRecipient(recp)
        tunel = state.exports.get_by_name(export)

        own = self.get_own_address(tunel.recipient.channel)
        cmd = spec.PrepareMigration(recipient=recp,
                                    migration_agent=own,
                                    host_cmd=self._get_host_cmd())
        req = self.initiate_protocol(protocol.Requester, tunel.recipient,
                                     cmd)
        return req.notify_finish()

    @replay.journaled
    def join_migrations(self, state, migration_ids, export=None):
        if not migration_ids:
            raise ValueError("Empty migration_ids: %r. This usually means "
                             "that none of the joined migrations is "
                             "completable", migration_ids)

        tunel = state.exports.get_by_name(export)

        own = self.get_own_address(tunel.recipient.channel)
        cmd = spec.JoinMigrations(migration_ids=migration_ids,
                                  migration_agent=own,
                                  host_cmd=self._get_host_cmd())
        req = self.initiate_protocol(protocol.Requester, tunel.recipient,
                                     cmd)
        return req.notify_finish()

    @manhole.expose()
    @replay.journaled
    def show_migration(self, state, migration_id, export=None):
        '''show_migration(migration_or_id, export=current) -> displays all
        the details about the migration object.'''
        migration_id = self._extract_migration_id(migration_id)
        tunel = state.exports.get_by_name(export)

        def extract_text(resp):
            return resp.text

        cmd = spec.ShowMigration(migration_id=migration_id)
        req = self.initiate_protocol(protocol.Requester, tunel.recipient, cmd)
        f = req.notify_finish()
        f.add_callback(extract_text)
        return f

    @manhole.expose()
    @replay.journaled
    def apply_migration(self, state, migration, export=None):
        '''
        apply_migration(migration) -> Apply the migration object.
        '''
        tunel = state.exports.get_by_name(export)
        task = self.initiate_protocol(ApplyMigration, tunel.recipient,
                                      migration)
        return task.notify_finish()

    @manhole.expose()
    @replay.journaled
    def apply_migration_step(self, state, migration_id, index, export=None):
        '''
        apply_migration_step(migration_or_id, step_index) -> Apply selected
        migration step (to be used for manual sorcery.
        '''
        tunel = state.exports.get_by_name(export)
        migration_id = self._extract_migration_id(migration_id)

        cmd = spec.ApplyMigrationStep(migration_id=migration_id,
                                      index=index)
        req = self.initiate_protocol(protocol.Requester, tunel.recipient, cmd)
        return req.notify_finish()

    @manhole.expose()
    @replay.mutable
    def spawn_next_agent(self, state):

        def handle_success(entry):
            f = self.remove_import_entry(entry)
            f.add_callback(fiber.drop_param, self.spawn_next_agent)
            return f

        def handle_failure(fail, entry):
            msg = ("Failed to start agent, import entry: %r" % entry)
            self.raise_alert(msg, alert.Severity.high)

        if state.spawn_running:
            return

        self._set_semaphore(True)

        entry = self.get_top_import_entry()
        if entry is not None:
            factory = descriptor.lookup(entry.agent_type)
            if factory is None:
                raise ValueError('Unknown agent type: %r' %
                                 (entry.agent_type, ))
            doc = factory()
            kwargs = dict()
            if entry.blackbox:
                kwargs['blackbox'] == entry.blackbox
            f = self.save_document(doc)
            f.add_callback(fiber.inject_param, 2, self.initiate_protocol,
                           start_agent.GloballyStartAgent, **kwargs)
            f.add_callback(fiber.call_param, 'notify_finish')
            f.add_callbacks(fiber.drop_param, handle_failure,
                            cbargs=(handle_success, entry),
                            ebargs=(entry, ))
            f.add_both(fiber.bridge_param, self._set_semaphore, False)

            return f

    ### Managing list of import entries stored in descriptor ###

    @replay.mutable
    def add_import_entry(self, state, entry):

        def do_add(desc, entry):
            desc.import_entries.append(entry)

        f = self.update_descriptor(do_add, entry)
        f.add_callback(fiber.drop_param, self.call_next, self.spawn_next_agent)
        return f

    @manhole.expose()
    @replay.mutable
    def remove_import_entry(self, state, index_or_entry):

        def do_remove(desc, entry):
            desc.import_entries.remove(entry)

        def trigger_event_if_empty():
            if self.get_top_import_entry() is None:
                self.callback_event('import_entries_empty', None)

        if isinstance(index_or_entry, int):
            entry = self.get_descriptor().import_entries[index_or_entry]
        else:
            entry = index_or_entry

        f = self.update_descriptor(do_remove, entry)
        f.add_callback(fiber.drop_param, trigger_event_if_empty)
        return f

    @manhole.expose()
    def get_top_import_entry(self):
        entries = self.get_descriptor().import_entries
        if entries:
            return entries[0]

    @manhole.expose()
    def show_import_entries(self):
        t = text_helper.Table(fields=('Agent Type', 'Blackbox', ),
                              lengths=(40, 100, ))
        return t.render((x.agent_type, pformat(x.blackbox), )
                        for x in self.get_descriptor().import_entries)

    def wait_for_empty_import_entries(self):
        f = fiber.succeed()
        desc = self.get_descriptor()
        if desc.import_entries:
            f.add_callback(fiber.drop_param,
                           self.wait_for_event, 'import_entries_empty')
        return f

    ### private ###

    @replay.mutable
    def _set_semaphore(self, state, val):
        state.spawn_running = val

    @replay.immutable
    def _get_host_cmd(self, state):
        # override this later in order to make migration agent in charge of
        # what command is run on the other side
        # If return None the default from the configuration of the export agent
        # will be executed
        return None

    def _render_shard_table(self, shards=None):

        def present(shard):
            hosts = "\n".join(shard.hosts)
            return (shard.agent_id, shard.shard, hosts)

        t = text_helper.Table(fields=('Agent ID', 'Shard', 'Hosts', ),
                              lengths=(40, 40, 40, ))
        return t.render(present(x) for x in shards)

    @replay.immutable
    def _get_exports(self, state):
        '''this is used only in tests'''
        return state.exports

    @replay.mutable
    def _got_local(self, state, recp):

        if len(recp) == 0:
            self.info("Failed discovering local export agent. But no "
                      "worries, you can retry by calling discover_local(). ")
            return

        return fiber.FiberList([self.handshake(r) for r in recp]).succeed()

    @replay.mutable
    def _add_export_entry(self, state, entry):
        state.exports.add_entry(entry)

    def _extract_migration_id(self, migration_or_id):
        if isinstance(migration_or_id, spec._MigrationResponse):
            return migration_or_id.ident
        else:
            return migration_or_id

    ### called by import agent ###

    @replay.journaled
    def migration_handle_import(self, state, agent_type=None, blackbox=None):

        def render_response(resp):
            return spec.HandleImportResponse()

        entry = ImportEntry(agent_type=agent_type,
                            blackbox=blackbox)

        f = self.add_import_entry(entry)
        f.add_callback(render_response)
        return f


@serialization.register
class ExportAgents(serialization.Serializable):

    def __init__(self):
        # name -> AgentEntry
        self.entries = dict()
        # name
        self.current = None

    def get_by_name(self, name=None):
        '''
        name=None indicates current tunnel.
        '''
        if name is None:
            current = self.get_current()
            if current is None:
                raise ValueError('No current tunel')
            else:
                return current
        return self.get(name)

    def get_current(self):
        return self.current

    def set_current(self, cur):
        if cur is None:
            self.current = None
        else:
            self.current = self.get(cur)

    def iter_entries(self):
        return self.entries.itervalues()

    def get(self, name):
        try:
            return self.entries[name]
        except KeyError as e:
            raise error.FeatError('Tunel with name %s not known.' % name,
                                  cause=e)

    def add_entry(self, entry):
        assert isinstance(entry, AgentEntry), entry
        self.entries[entry.name] = entry

    def remove_entry(self, name):
        entry = self.get(name)
        del(self.entries[entry.name])
        if self.current == entry:
            self.set_current(None)

    def __eq__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return self.current == other.current and \
               self.entries == other.entries

    def __ne__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return not self.__eq__(other)


@serialization.register
class AgentEntry(formatable.Formatable):

    formatable.field('recipient', None)
    formatable.field('name', None)
    formatable.field('version', None)


class ApplyMigration(task.BaseTask):

    timeout = None

    @replay.entry_point
    def initiate(self, state, recp, migration):
        state.recipient = recp
        self._store_migration(migration)

        return self._next()

    @replay.journaled
    def _next(self, state):
        if not state.migration.completed:
            cmd = spec.ApplyNextMigrationStep(
                migration_id=state.migration.ident)
            f = state.agent.wait_for_empty_import_entries()
            f.add_callback(fiber.drop_param, self._request, cmd)
            f.add_callback(self._store_migration)
            f.add_callback(fiber.drop_param, self._next)
            return f
        else:
            cmd = spec.ForgetMigration(
                migration_id=state.migration.ident)
            f = self._request(cmd)
            f.add_callback(fiber.override_result, "All ok!")
            return f

    @replay.mutable
    def _request(self, state, cmd):
        req = state.agent.initiate_protocol(
            protocol.Requester, state.recipient, cmd)
        return req.notify_finish()

    @replay.mutable
    def _store_migration(self, state, migration):
        # migration here is a child instance of spec._MigrationResponse
        state.migration = migration


@descriptor.register('migration_agent')
class Descriptor(descriptor.Descriptor):

    # agent_id -> [PendingNotification]
    formatable.field('pending_notifications', dict())
    # [ImportEntry]
    formatable.field('import_entries', list())


@serialization.register
class ImportEntry(formatable.Formatable):
    type_name = 'import_entry'

    formatable.field('agent_type', None)
    formatable.field('blackbox', None)
