from feat.agents.base import agent, replay, recipient, task, descriptor
from feat.agents.common import start_agent
from feat.common import (fiber, serialization, formatable, manhole,
                         error, text_helper, )
from feat.agents.migration import protocol, spec


@agent.register('migration_agent')
class MigrationAgent(agent.BaseAgent):

    @replay.mutable
    def initiate(self, state):
        state.medium.register_interest(protocol.Replier)
        state.exports = ExportAgents()

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

    @replay.journaled
    def handshake(self, state, recp):
        req = self.initiate_protocol(
            protocol.Requester, recp, spec.Handshake())
        return req.notify_finish()

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

    @replay.journaled
    def prepare_host_migration(self, state, recp, export=None):
        '''prepare_host_migration(self, recp, export=current) -> creates
        migration object representing full shutdown of the host with recp.'''
        recp = recipient.IRecipient(recp)
        tunel = state.exports.get_by_name(export)

        own = self.get_own_address()
        cmd = spec.PrepareMigration(recipient=recp,
                                    migration_agent=own,
                                    host_cmd=self._get_host_cmd())
        req = self.initiate_protocol(protocol.Requester, tunel.recipient,
                                     cmd)
        return req.notify_finish()

    @replay.journaled
    def join_migrations(self, state, migration_ids, export=None):
        tunel = state.exports.get_by_name(export)

        own = self.get_own_address()
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

    ### private ###

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

        def parse(response):
            return AgentEntry(recipient=recp,
                              name=response.name,
                              version=response.version)

        if len(recp) == 0:
            raise error.FeatError("Export service not found.")
        fibers = list()
        for r in recp:
            f = self.handshake(r)
            f.add_callback(parse)
            f.add_callback(self._add_export_entry)
            fibers.append(f)
        f = fiber.FiberList(fibers)
        return f.succeed()

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

        factory = descriptor.lookup(agent_type)
        if factory is None:
            raise ValueError('Unknown agent type: %r' % (agent_type, ))
        doc = factory()
        kwargs = dict()
        if blackbox:
            kwargs['blackbox'] == blackbox
        f = self.save_document(doc)
        f.add_callback(fiber.inject_param, 2, self.initiate_protocol,
                       start_agent.GloballyStartAgent, **kwargs)
        f.add_callback(fiber.call_param, 'notify_finish')
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
            req = self._request(cmd)
            f = req.notify_finish()
            f.add_callback(self._store_migration)
            f.add_callback(fiber.drop_param, self._next)
            return f
        else:
            cmd = spec.ForgetMigration(
                migration_id=state.migration.ident)
            req = self._request(cmd)
            f = req.notify_finish()
            f.add_callback(fiber.override_result, "All ok!")
            return f

    @replay.immutable
    def _request(self, state, cmd):
        return state.agent.initiate_protocol(
            protocol.Requester, state.recipient, cmd)

    @replay.mutable
    def _store_migration(self, state, migration):
        # migration here is a child instance of spec._MigrationResponse
        state.migration = migration


@descriptor.register('migration_agent')
class Descriptor(descriptor.Descriptor):

    # agent_id -> [PendingNotification]
    formatable.field('pending_notifications', dict())
