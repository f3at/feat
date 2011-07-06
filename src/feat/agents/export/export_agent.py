import operator
import uuid
import copy

from feat.agents.base import (agent, replay, view, manager,
                              message, task, document, dbtools, sender, )
from feat.agents.common import (rpc, export, host, start_agent, migration, )
from feat.common import (formatable, serialization, log, fiber,
                         text_helper, manhole, first, )

from feat.interface.recipient import *


Migratability = export.Migratability


class Partners(agent.Partners):
    pass


@agent.register('export_agent')
class ExportAgent(agent.BaseAgent, sender.AgentMixin):

    partners_class = Partners

    migratability = export.Migratability.not_migratable

    @replay.mutable
    def initiate(self, state):
        # result of the view query for th shard structure
        state.shards = list()

    ### Public exposed methods ###

    @manhole.expose()
    @replay.journaled
    def show_shard_structure(self, state):
        f = self.get_shard_structure()
        f.add_callback(fiber.drop_param, self._render_shard_table)
        return f

    @manhole.expose()
    def show_migration(self, migration):
        # TODO: This should be moved to migration agent when it is done
        resp = []
        if migration.is_completable():
            resp += ["Migration is completable."]
        else:
            resp += ["Migration is NOT completable. Problem is: %r." %
                     migration.problem]
        recp += ["Migration import agent recp: %r" % migration.migration_agent]
        resp += ["Migration check in entries."]
        t = text_helper.Table(
            fields=("Agent type", "Agent_id", "Shard",
                    "Migratability", "Dependencies", "Hostname"),
            lengths=(20, 40, 40, 20, 50, 40))
        text = t.render(((x.agent_type, x.agent_id, x.shard,
                          x.migratability.name, "\n".join(x.dependencies),
                          x.hostname)
                         for x in migration.checkins))
        resp += [text]
        resp += [""]
        resp += ["Migration steps."]
        t = text_helper.Table(
            fields=("Agent_id", "Shard", "Strategy", "Applied",
                    "Cancelled", "Failure"),
            lengths=(40, 40, 20, 15, 15, 40))
        text = t.render(((x.recipient.key, x.recipient.shard,
                          x.strategy.name, x.applied, x.cancelled,
                          x.failure or "")
                         for x in migration.steps))
        resp += [text]
        return "\n".join(resp)

    @replay.journaled
    def get_shard_structure(self, state):
        f = self.query_view(ShardStructure)
        f.add_callback(self._got_shards)
        return f

    @rpc.publish
    @manhole.expose()
    @replay.journaled
    def prepare_migration(self, state, recp, host_cmd=None,
                          migration_agent=None):
        recp = IRecipient(recp)
        manager = self.initiate_protocol(CheckInManager, recp,
                                         host_cmd=host_cmd,
                                         migration_agent=migration_agent)
        f = manager.notify_finish()
        f.add_callback(fiber.bridge_param, self.get_shard_structure)
        f.add_callback(self._topology_fixes)
        return f

    @replay.immutable
    def _topology_fixes(self, state, migration):
        '''
        This is part of algorithms logic which is not static. It combines
        information from the shard view and migration to figure out if
        migration involves terminating the shard(s). In this case it removes
        the steps for migrating structural agents (strategy "locally") from
        the migration plan.
        '''
        kill_list = migration.get_kill_list()
        for shard, hosts in kill_list.iteritems():
            shard_view = first(x for x in state.shards if x.shard == shard)
            if shard_view is None:
                self.warning('Shard %r has not been found in shard view. '
                             'This is really strange! Shard structure taken '
                             'for analizing: \n%s', shard,
                             self._render_shard_table)
                continue
            shard_is_terminating = (set(hosts) == set(shard_view.hosts))
            if shard_is_terminating:
                self.log('Detected that shard %r will be terminating, removing'
                         ' local steps of the migration.', shard)
                migration = migration.remove_local_migrations(shard)
        return migration

    @rpc.publish
    @manhole.expose()
    @replay.journaled
    def cancel_migration(self, state, migration):
        return migration.cancel(self)

    @manhole.expose()
    @replay.journaled
    def apply_next_step(self, state, migration):
        if migration.is_complete():
            raise ValueError("apply_next_step() called on migration, "
                             "which is already completed.")
        step = migration.get_next_step()
        return self.apply_migration_step(migration, step)

    @manhole.expose()
    @replay.journaled
    def apply_migration_step(self, state, migration, step):
        if isinstance(step, int):
            step = migration.steps[step]
        if not isinstance(step, MigrationStep):
            raise AttributeError("Second parameter expected to be a "
                                 "MigrationStep or an index in step of"
                                 "migration, got %r instead." % step)
        task = self.initiate_protocol(ApplyMigrationStep, migration, step,
                                      state.notification_sender)
        return task.notify_finish()

    @manhole.expose()
    @replay.journaled
    def lock_host(self, state, recp):
        return self.call_remote(recp, 'set_migrating', 'manual')

    @manhole.expose()
    @replay.journaled
    def unlock_host(self, state, recp):
        return self.call_remote(recp, 'unregister_from_migration', 'manual')

    ### private ###

    @replay.mutable
    def _got_shards(self, state, shards):
        state.shards = shards
        return state.shards

    @replay.immutable
    def _render_shard_table(self, state, shards=None):

        def present(shard):
            hosts = "\n".join(shard.hosts)
            return (shard.agent_id, shard.shard, hosts)

        shards = shards or state.shards
        t = text_helper.Table(fields=('Agent ID', 'Shard', 'Hosts', ),
                              lengths=(40, 40, 40, ))
        return t.render(present(x) for x in shards)


@view.register
@serialization.register
class ShardStructure(view.FormatableView):

    name = "shard_structure"

    def map(doc):
        if doc['.type'] == 'shard_agent':
            hosts = list()
            for p in doc['partners']:
                if p['.type'] == 'shard->host':
                    hosts.append(p['recipient']['key'])
            yield doc['shard'], dict(agent_id=doc['_id'],
                                     shard=doc['shard'],
                                     hosts=hosts)
    view.field('agent_id', None)
    view.field('shard', None)
    view.field('hosts', list())


class ApplyMigrationStep(task.BaseTask):

    @replay.entry_point
    def initiate(self, state, migration, step, sender):
        if not isinstance(migration, Migration):
            raise TypeError("Expected argument 1 to be Migration, got %r "
                            "instead." % migration)
        if step.inactive:
            raise ValueError("Step %r is already applied or cancelled" % step)
        state.migration = migration
        state.step = step
        state.sender = sender

        method_name = "migrate_%s" % (state.step.strategy.name, )
        method = getattr(self, method_name, None)
        if not callable(method):
            raise NotImplementedError("Unknown migration strategy %s" %
                                      state.step.strategy.name)
        f = method()
        f.add_callbacks(callback=fiber.drop_param,
                        cbargs=(step.set_applied, ),
                        errback=step.set_failure)
        f.add_callback(fiber.override_result, state.migration)
        return f

    @replay.mutable
    def migrate_locally(self, state):
        f = self._prepare_restart()
        f.add_callback(self._start_local)
        f.add_callback(self._send_restarted_notifications)
        return f

    @replay.mutable
    def migrate_host(self, state):
        f = state.agent.call_remote(state.step.recipient, 'upgrade',
                                    state.migration.host_cmd)
        return f

    @replay.mutable
    def migrate_globally(self, state):
        f = self._prepare_restart()
        f.add_callback(self._start_global)
        f.add_callback(self._send_restarted_notifications)
        return f

    @replay.mutable
    def migrate_exportable(self, state):
        f = self._prepare_restart(hard=False)
        if state.migration.migration_agent:
            f.add_callback(fiber.inject_param, 3,
                           migration.handle_import,
                           state.migration.migration_agent,
                           state.descriptor.document_type)
        f.add_callback(fiber.override_result, None)
        return f

    @replay.mutable
    def migrate_shutdown(self, state):
        f = self._request_terminate()
        return f

    ### private ###

    @replay.mutable
    def _prepare_restart(self, state, hard=True):
        f = self._get_blackbox()
        if hard:
            f.add_callback(fiber.bridge_param, self._request_terminate_hard)
        else:
            f.add_callback(fiber.bridge_param, self._request_terminate)
        f.add_callback(fiber.bridge_param, self._fetch_descriptor)
        return f

    @replay.journaled
    def _fetch_descriptor(self, state):
        f = state.agent.get_document(state.step.agent_id)
        f.add_callback(self._store_descriptor)
        return f

    @replay.mutable
    def _store_descriptor(self, state, desc):
        state.descriptor = desc

    @replay.journaled
    def _get_blackbox(self, state):
        return state.agent.call_remote(state.step.recipient,
                                       "get_migration_blackbox")

    @replay.journaled
    def _request_terminate_hard(self, state):
        return state.agent.call_remote(state.step.recipient,
                                       "terminate_hard")

    @replay.journaled
    def _request_terminate(self, state):
        return state.agent.call_remote(state.step.recipient,
                                       "terminate")

    @replay.journaled
    def _start_local(self, state, blackbox):
        kwargs = dict()
        if blackbox:
            kwargs['blackbox'] = blackbox
        return host.start_agent_in_shard(state.agent, state.descriptor,
                                         state.step.recipient.shard,
                                         **kwargs)

    @replay.journaled
    def _start_global(self, state, blackbox):
        kwargs = dict()
        if blackbox:
            kwargs['blackbox'] = blackbox
        task = state.agent.initiate_protocol(start_agent.GloballyStartAgent,
                                             state.descriptor, **kwargs)
        return task.notify_finish()

    @replay.mutable
    def _send_restarted_notifications(self, state, new_address):
        self.log("Sending 'restarted' notifications to the partners, "
                 "which are: %r", state.descriptor.partners)
        notifications = list()
        for partner in state.descriptor.partners:
            notifications.append(sender.PendingNotification(
                recipient=IRecipient(partner),
                type='restarted',
                origin=state.step.recipient,
                payload=new_address))
        return state.sender.notify(notifications)


class CheckInManager(manager.BaseManager):

    protocol_id = 'check_in'

    @replay.entry_point
    def initiate(self, state, host_cmd=None, migration_agent=None):
        state.recipient = state.medium.get_recipients()
        if host_cmd is None:
            host_cmd = state.agent.get_configuration().default_host_cmd
        state.migration = Migration(
            host_cmd=host_cmd,
            migration_agent=migration_agent)
        announce = message.Announcement()
        announce.payload = state.migration
        state.medium.announce(announce)

    @replay.entry_point
    def closed(self, state):
        bid = state.medium.get_bids()[0]
        entries = bid.payload
        for entry in entries:
            state.migration.checkins.add_entry(entry)
        state.migration.analyze(state.recipient)
        if state.migration.is_completable():
            state.medium.grant((bid, message.Grant()))
        else:
            state.medium.terminate(state.migration)

    def expired(self):
        self._checkin_failed("Timeout expired.")

    def aborted(self):
        self._checkin_failed("Timeout expired.")

    def cancelled(self, cancellation):
        self._checkin_failed("Cancelled, reason: %s" % cancellation.reason)

    @replay.mutable
    def _checkin_failed(self, state, reason):
        state.migration.set_problem(reason)
        state.medium.terminate(state.migration)

    @replay.entry_point
    def completed(self, state, reports):
        return state.migration


class BaseNotMigratable(Exception):

    def __init__(self, *args, **kwargs):
        self.partial_solution = kwargs.pop('partial_solution', None)
        Exception.__init__(self, *args, **kwargs)


class NotCheckedIn(BaseNotMigratable):
    pass


class NotMigratable(BaseNotMigratable):
    pass


class RecursiveDependency(BaseNotMigratable):
    pass


@serialization.register
class MigrationStep(formatable.Formatable):

    formatable.field('recipient', None)
    formatable.field('strategy', None)
    formatable.field('applied', False)
    formatable.field('cancelled', False)
    formatable.field('failure', None)

    def cancel(self, agent, migration_id):
        f = agent.call_remote(self.recipient,
                              'unregister_from_migration', migration_id)
        f.add_callback(fiber.drop_param, self.set_cancelled)
        f.add_errback(self.set_failure)
        return f

    @property
    def agent_id(self):
        return self.recipient.key

    @property
    def inactive(self):
        return self.applied or self.cancelled

    def set_cancelled(self):
        self.cancelled = True

    def set_failure(self, fail):
        self.failure = fail

    def set_applied(self):
        self.applied = True


@serialization.register
class CheckinList(serialization.Serializable, log.Logger):

    type_name = 'export-checkin-list'

    def __init__(self, logger):
        # agent_id -> CheckinEntry
        log.Logger.__init__(self, logger)
        self.data = dict()

    def __iter__(self):
        return self.data.itervalues()

    def add_entry(self, entry):
        self.data[entry.agent_id] = entry

    def generate_migration(self, agent_id):
        resp = list()
        data = copy.deepcopy(self.data)
        while True:
            try:
                step = self._generate_next_step(agent_id, data)
                resp.append(step)
                extra = self._apply_entry(data, step)
                if extra:
                    resp += extra
                if step.agent_id == agent_id:
                    break
            except BaseNotMigratable as e:
                factory = type(e)
                msg = str(e)
                raise factory(msg, partial_solution=resp)
        return resp

    ### private ###

    def _generate_next_step(self, agent_id, data, stack=[]):
        '''
        Should be used to figure out the next step to do get rid of the agent.
        '''
        self.log("Generating next step to migrate agent id: %r. "
                 "The stack is %r.", agent_id, stack)
        entry = data.get(agent_id, None)
        if not entry:
            self._raise_not_checkin(agent_id)
        self.log("Entry for the agent: %r", entry)
        if entry.migratability == Migratability.not_migratable:
            raise NotMigratable("Agent %s id: %r cannot be migrated."
                                % (entry.agent_type, agent_id, ))
        if not entry.dependencies:
            return self._generate_step(entry)

        exc = None
        self.log('Inspecting dependencies of the entry.')
        for dependency in entry.get_dependant_entries(data):
            try:
                if not isinstance(dependency, export.CheckinEntry):
                    self._raise_not_checkin(dependency)
                if dependency.agent_id in stack:
                    msg = ("Agent %s id: %r and %s id: %r depend on each other"
                           % (entry.agent_type, entry.agent_id,
                              dependency.agent_type, dependency.agent_id, ))
                    raise RecursiveDependency(msg)
                new_stack = stack + [agent_id]
                return self._generate_next_step(dependency.agent_id, data,
                                                new_stack)
            except BaseNotMigratable as e:
                exc = e
        raise exc

    def _raise_not_checkin(self, agent_id):
        raise NotCheckedIn("Agent %r is not checked in" % (agent_id, ))

    def _apply_entry(self, data, step):
        self.log('Removing agent id: %r from the list', step.agent_id)
        a_id = step.agent_id
        extra_steps = list()
        del(data[a_id])
        for key in data.keys():
            entry = data.get(key, None)
            if not entry:
                # entry has been removed by the nested iteration
                continue
            if a_id in entry.dependencies:
                entry.remove_dependency(a_id)
                if not entry.dependencies and \
                   entry.migratability == export.Migratability.shutdown:
                    sstep = self._generate_step(entry)
                    extra_steps.append(sstep)
                    extra = self._apply_entry(data, sstep)
                    if extra:
                        extra_steps += extra

        return extra_steps

    def _generate_step(self, entry):
        recp = IRecipient(entry)
        return MigrationStep(recipient=recp,
                             strategy=entry.migratability)

    def __eq__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return self.data == other.data

    def __ne__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return self.data != other.data


@serialization.register
class Migration(serialization.Serializable):

    def __init__(self, host_cmd=None, migration_agent=None):
        self.host_cmd = host_cmd
        # CheckinList
        self.checkins = None
        # [MigrationStep]
        self.steps = None
        # BaseNotMigratable or None
        self.problem = None
        self.ident = None
        self.analized = False
        self.migration_agent = migration_agent and IRecipient(migration_agent)

        self.reset()

    def reset(self):
        self.checkins = CheckinList(None)
        self.steps = None
        self.problem = None
        self.ident = self._generate_ident()
        self.analized = False

    def analyze(self, recp):
        '''
        Analyzes the checkins. Generates the migration steps and sets flags
        saying if this is doable or not.
        '''
        try:
            agent_id = IRecipient(recp).key
            self.steps = self.checkins.generate_migration(agent_id)
        except BaseNotMigratable as e:
            self.set_problem(e)
            self.steps = e.partial_solution
        self.analized = True

    def cancel(self, agent):
        fibers = list()
        for step in self.steps:
            fibers.append(step.cancel(agent, self.ident))
        f = fiber.FiberList(fibers)#, consumeErrors=True)
        return f.succeed()

    def set_problem(self, problem):
        self.problem = problem
        self.analized = True

    def is_complete(self):
        self._ensure_analized('is_complete()')
        return all(map(operator.attrgetter('inactive'), self.steps))

    def is_completable(self):
        self._ensure_analized('is_completable()')
        return self.problem is None

    def get_next_step(self):
        self._ensure_analized('get_next_step()')
        for step in self.steps:
            if not step.inactive:
                return step
        raise ValueError("Could not find the next step to apply.")

    def get_kill_list(self):
        '''
        Contruct the dictionary shard_id -> [list_of_hosts]
        representing which hosts are terminated during the procedure.
        '''
        resp = dict()
        for step in self.steps:
            if step.strategy == Migratability.host:
                shard = step.recipient.shard
                if shard not in resp:
                    resp[shard] = list()
                resp[shard].append(step.recipient.key)
        return resp

    def remove_local_migrations(self, shard):
        '''
        Removes all steps with "locally" strategy for the given shard.
        '''
        self.steps = [x for x in self.steps
                      if not (x.strategy == Migratability.locally and
                              x.recipient.shard == shard)]
        return self

    ### private ###

    def _ensure_analized(self, method):
        if not self.analized:
            raise ValueError('Before calling %s you should call analyze()' %
                             method)

    @replay.side_effect
    def _generate_ident(self):
        return str(uuid.uuid1())

    def __eq__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return self.checkins == other.checkins and \
               self.host_cmd == other.host_cmd and \
               self.steps == other.steps and \
               self.problem == other.problem and \
               self.ident == other.ident and \
               self.analized == other.analized

    def __ne__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return not self.__eq__(other)


@document.register
class ExportAgentConfiguration(document.Document):

    document_type = 'export_agent_conf'
    document.field('doc_id', u'export_agent_conf', '_id')
    document.field('notification_period', 12)
    document.field('default_host_cmd', '/bin/true')


dbtools.initial_data(ExportAgentConfiguration)
