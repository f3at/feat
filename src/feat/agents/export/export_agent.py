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
import operator
import uuid
import copy

import feat
from feat.agents.base import (agent, replay, manager, contractor,
                              message, task, document, dbtools, sender, )
from feat.agents.common import (rpc, export, host, start_agent, )
from feat.common import (formatable, serialization, log, fiber,
                         text_helper, manhole, first, )
from feat.agents.migration import protocol, spec

from feat.interface.recipient import IRecipients, IRecipient


Migratability = export.Migratability


class Partners(agent.Partners):
    pass


@agent.register('export_agent')
class ExportAgent(agent.BaseAgent, sender.AgentMixin):

    partners_class = Partners

    migratability = export.Migratability.not_migratable

    @replay.mutable
    def initiate(self, state):
        state.medium.enable_channel('tunnel')
        # result of the view query for th shard structure
        state.shards = list()
        # registry of know migrations to be able to speak with
        # migration agent using only identifier
        # migration.ident -> migration
        state.known_migrations = dict()

        state.medium.register_interest(protocol.Replier)
        i = state.medium.register_interest(
            contractor.Service(protocol.Replier))
        i.bind_to_lobby()

    ### methods called by Migration Agent ###

    @replay.journaled
    def migration_handshake(self, state):
        '''
        Called by the migtration agent to get to know us.
        '''
        config = state.medium.get_configuration()
        return spec.HandshakeResponse(name=config.sitename,
                                      version=feat.version)

    @replay.journaled
    def migration_get_shard_structure(self, state):

        def render_response(shards):
            return spec.GetShardStructureResponse(shards=shards)

        f = self.get_shard_structure()
        f.add_callback(render_response)
        return f

    @replay.journaled
    def migration_prepare_migration(self, state, recipient=None,
                                    migration_agent=None, host_cmd=None):
        f = self.prepare_migration(recipient, host_cmd=host_cmd,
                                   migration_agent=migration_agent)
        f.add_callback(self._render_migration, spec.PrepareMigrationResponse)
        return f

    @replay.journaled
    def migration_join_migrations(self, state, migration_ids=[],
                                  migration_agent=None, host_cmd=None):
        f = self.join_migrations(migration_ids, host_cmd=host_cmd,
                                 migration_agent=migration_agent)
        f.add_callback(self._render_migration, spec.JoinMigrationsResponse)
        return f

    @replay.journaled
    def migration_show_migration(self, state, migration_id=None):
        text = self.show_migration(migration_id)
        return spec.ShowMigrationResponse(text=text)

    @replay.journaled
    def migration_apply_next_step(self, state, migration_id=None):
        f = self.apply_next_step(migration_id)
        f.add_callback(self._render_migration,
                       spec.ApplyNextMigrationStepResponse)
        return f

    @replay.mutable
    def migration_forget_migration(self, state, migration_id=None):
        self.forget_migration(migration_id)
        return spec.ForgetMigrationResponse()

    @replay.mutable
    def migration_apply_migration_step(self, state, migration_id=None,
                                       index=None):
        f = self.apply_migration_step(migration_id, index)
        f.add_callback(self._render_migration,
                       spec.ApplyMigrationStepResponse)
        return f

    ### helper method used by exposed methods ###

    def _render_migration(self, migration, factory):
            completable = migration.is_completable()
            completed = migration.is_complete()

            return factory(ident=migration.get_id(),
                           completable=completable,
                           completed=completed)

    ### Public exposed methods ###

    @replay.immutable
    def get_known_migrations(self, state):
        return state.known_migrations.values()

    @manhole.expose()
    @replay.mutable
    def join_migrations(self, state, migrations_or_ids, host_cmd=None,
                        migration_agent=None):
        migrations = map(self._get_migration, migrations_or_ids)
        for migration in migrations:
            if not migration.is_completable():
                prob = migration.get_problem()
                return fiber.fail(prob)

        if host_cmd is None:
            host_cmd = self.get_configuration().default_host_cmd
        resp = Migration(self,
            host_cmd=host_cmd,
            migration_agent=migration_agent)

        recipients = list()
        for migration in migrations:
            recipients += list(migration.get_analyzed())
            for entry in migration.get_checkin_entries():
                resp.checkin(entry)

        resp.analyze(recipients)

        [self.forget_migration(x) for x in migrations]
        f = self.get_shard_structure()
        f.add_callback(fiber.drop_param, self._topology_fixes, resp)
        f.add_callback(self._register_migration)
        return f

    @manhole.expose()
    @replay.mutable
    def forget_migration(self, state, migration_or_id):
        migration = self._get_migration(migration_or_id)
        del(state.known_migrations[migration.get_id()])

    @manhole.expose()
    def show_migration(self, migration_or_id):
        migration = self._get_migration(migration_or_id)
        resp = []
        if migration.is_completable():
            resp += ["Migration is completable."]
        else:
            resp += ["Migration is NOT completable. Problem is: %r." %
                     migration.get_problem()]
        resp += ["Migration import agent recp: %r" %
                 migration.get_migration_agent()]
        resp += ["Migration check in entries."]
        t = text_helper.Table(
            fields=("Agent type", "Agent_id", "Shard",
                    "Migratability", "Dependencies", "Hostname"),
            lengths=(20, 40, 40, 20, 50, 40))
        text = t.render(((x.agent_type, x.agent_id, x.shard,
                          x.migratability.name, "\n".join(x.dependencies),
                          x.hostname)
                         for x in migration.get_checkin_entries()))
        resp += [text]
        resp += [""]
        resp += ["Migration steps."]
        t = text_helper.Table(
            fields=("Agent_id", "Shard", "Strategy", "Applied",
                    "Cancelled", "Failure"),
            lengths=(40, 40, 20, 15, 15, 40))
        text = t.render(((x.recipient.key, x.recipient.route,
                          x.strategy.name, x.applied, x.cancelled,
                          x.failure or "")
                         for x in migration.get_steps()))
        resp += [text]
        return "\n".join(resp)

    @replay.journaled
    def get_shard_structure(self, state):
        f = self.query_view(spec.ShardStructure)
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
        f.add_callback(self._register_migration)
        return f

    @rpc.publish
    @manhole.expose()
    @replay.journaled
    def cancel_migration(self, state, migration_or_id):
        migration = self._get_migration(migration_or_id)
        return migration.cancel()

    @manhole.expose()
    @replay.journaled
    def apply_next_step(self, state, migration_or_id):
        migration = self._get_migration(migration_or_id)
        if migration.is_complete():
            raise ValueError("apply_next_step() called on migration, "
                             "which is already completed.")
        step = migration.get_next_step()
        return self.apply_migration_step(migration, step)

    @manhole.expose()
    @replay.journaled
    def apply_migration_step(self, state, migration_or_id, step):
        migration = self._get_migration(migration_or_id)

        if isinstance(step, int):
            step = migration.get_steps()[step]
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
        return self.call_remote(recp, 'unregister_from_migration', ['manual'])

    ### private ###

    @replay.mutable
    def _register_migration(self, state, migration):
        state.known_migrations[migration.get_id()] = migration
        return migration

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
                             'for analyzing: \n%s', shard,
                             state.shards)
                continue
            shard_is_terminating = (set(hosts) == set(shard_view.hosts))
            if shard_is_terminating:
                self.log('Detected that shard %r will be terminating, removing'
                         ' local steps of the migration.', shard)
                migration = migration.remove_local_migrations(shard)
        return migration

    @replay.immutable
    def _get_migration(self, state, migration_or_id):
        if isinstance(migration_or_id, Migration):
            return migration_or_id
        else:
            return state.known_migrations[migration_or_id]

    @replay.mutable
    def _got_shards(self, state, shards):
        state.shards = shards
        return state.shards


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

        index = state.migration.get_steps().index(state.step)

        method_name = "migrate_%s" % (state.step.strategy.name, )
        method = getattr(self, method_name, None)
        if not callable(method):
            raise NotImplementedError("Unknown migration strategy %s" %
                                      state.step.strategy.name)
        f = method()
        f.add_callbacks(callback=fiber.drop_param,
                        cbargs=(migration.set_step_applied, index, ),
                        errback=migration.set_step_failure,
                        ebargs=(index, ))
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
                                    state.migration.get_host_cmd())
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
        f.add_callback(self._handle_export)
        return f

    @replay.mutable
    def migrate_shutdown(self, state):
        f = self._request_terminate()
        return f

    ### private ###

    @replay.journaled
    def _handle_export(self, state, blackbox):
        mig_recp = state.migration.get_migration_agent()
        if mig_recp is None:
            return fiber.succeed()
        cmd = spec.HandleImport(agent_type=state.descriptor.document_type,
                                blackbox=blackbox)
        req = state.agent.initiate_protocol(protocol.Requester, mig_recp, cmd)
        f = req.notify_finish()
        f.add_callback(fiber.override_result, None)
        return f

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
                                         state.step.recipient.route,
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
        state.migration = Migration(state.agent,
            host_cmd=host_cmd,
            migration_agent=migration_agent)
        announce = message.Announcement()
        announce.payload = dict(migration_id=state.migration.get_id())
        state.medium.announce(announce)

    @replay.entry_point
    def closed(self, state):
        bid = state.medium.get_bids()[0]
        entries = bid.payload
        for entry in entries:
            state.migration.checkin(entry)
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
    formatable.field('migration_ids', list())

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
        if entry.agent_id not in self.data:
            self.data[entry.agent_id] = entry
        else:
            self.data[entry.agent_id].migration_ids += entry.migration_ids

    def generate_migration(self, *agent_ids):
        resp = list()
        data = copy.deepcopy(self.data)
        for agent_id in agent_ids:
            self._single_agent_migration(agent_id, resp, data)
        return resp

    def _single_agent_migration(self, agent_id, resp, data):
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
                             strategy=entry.migratability,
                             migration_ids=entry.migration_ids)

    def __eq__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return self.data == other.data

    def __ne__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return self.data != other.data


@serialization.register
class Migration(replay.Replayable):

    def init_state(self, state, agent, host_cmd=None, migration_agent=None):
        state.agent = agent
        state.host_cmd = host_cmd
        # CheckinList
        state.checkins = None
        # [MigrationStep]
        state.steps = None
        # BaseNotMigratable or None
        state.problem_type = None
        state.problem_msg = None
        state.ident = None
        state.analyzed = False
        state.migration_agent = migration_agent and IRecipient(migration_agent)

        self.reset()

    @replay.mutable
    def reset(self, state):
        state.checkins = CheckinList(None)
        state.steps = None
        state.problem_type = None
        state.problem_msg = None
        state.ident = self._generate_ident()
        state.analyzed = False

    @replay.mutable
    def checkin(self, state, entry):
        state.checkins.add_entry(entry)

    @replay.immutable
    def get_checkin_entries(self, state):
        return state.checkins

    @replay.immutable
    def get_steps(self, state):
        return state.steps

    @replay.immutable
    def get_id(self, state):
        return state.ident

    @replay.immutable
    def get_analyzed(self, state):
        return state.analyzed

    @replay.immutable
    def get_problem(self, state):
        if state.problem_type is not None:
            return state.problem_type(state.problem_msg)

    @replay.immutable
    def get_migration_agent(self, state):
        return state.migration_agent

    @replay.immutable
    def get_host_cmd(self, state):
        return state.host_cmd

    @replay.mutable
    def analyze(self, state, recipients):
        '''
        Analyzes the checkins. Generates the migration steps and sets flags
        saying if this is doable or not.
        '''
        try:
            recipients = IRecipients(recipients)
            agent_ids = [recp.key for recp in recipients]
            state.steps = state.checkins.generate_migration(*agent_ids)
        except BaseNotMigratable as e:
            self.set_problem(e)
            state.steps = e.partial_solution
        state.analyzed = recipients

    @replay.mutable
    def cancel(self, state):
        fibers = list()
        for step, index in zip(state.steps, range(len(state.steps))):
            fibers.append(self.cancel_step(index))
        f = fiber.FiberList(fibers)
        f.add_callback(fiber.override_result, self)
        return f.succeed()

    @replay.immutable
    def cancel_step(self, state, index):
        step = state.steps[index]
        f = state.agent.call_remote(
            step.recipient, 'unregister_from_migration', step.migration_ids)
        f.add_callback(fiber.drop_param, self.set_step_cancelled, index)
        f.add_errback(self.set_step_failure, index)
        return f

    @replay.mutable
    def set_step_cancelled(self, state, index):
        step = state.steps[index]
        step.set_cancelled()

    @replay.mutable
    def set_step_failure(self, state, fail, index):
        step = state.steps[index]
        step.set_failure(fail)

    @replay.mutable
    def set_step_applied(self, state, index):
        step = state.steps[index]
        step.set_applied()

    @replay.mutable
    def set_problem(self, state, problem):
        state.problem_type = type(problem)
        state.problem_msg = str(problem)

    @replay.immutable
    def is_complete(self, state):
        self._ensure_analyzed('is_complete()')
        return all(map(operator.attrgetter('inactive'), state.steps))

    @replay.immutable
    def is_completable(self, state):
        self._ensure_analyzed('is_completable()')
        return state.problem_type is None

    @replay.immutable
    def get_next_step(self, state):
        self._ensure_analyzed('get_next_step()')
        for step in state.steps:
            if not step.inactive:
                return step
        raise ValueError("Could not find the next step to apply.")

    @replay.immutable
    def get_kill_list(self, state):
        '''
        Contruct the dictionary shard_id -> [list_of_hosts]
        representing which hosts are terminated during the procedure.
        '''
        resp = dict()
        for step in state.steps:
            if step.strategy == Migratability.host:
                shard = step.recipient.route
                if shard not in resp:
                    resp[shard] = list()
                resp[shard].append(step.recipient.key)
        return resp

    @replay.mutable
    def remove_local_migrations(self, state, shard):
        '''
        Removes all steps with "locally" strategy for the given shard.
        '''
        state.steps = [x for x in state.steps
                       if not (x.strategy == Migratability.locally and
                               x.recipient.route == shard)]
        return self

    ### private ###

    @replay.immutable
    def _ensure_analyzed(self, state, method):
        if not state.analyzed:
            raise ValueError('Before calling %s you should call analyze()' %
                             method)

    @replay.side_effect
    def _generate_ident(self):
        return str(uuid.uuid1())


@document.register
class ExportAgentConfiguration(document.Document):

    document_type = 'export_agent_conf'
    document.field('doc_id', u'export_agent_conf', '_id')
    document.field('notification_period', 12)
    document.field('default_host_cmd', '/bin/true')
    document.field('sitename', 'local')


dbtools.initial_data(ExportAgentConfiguration)
