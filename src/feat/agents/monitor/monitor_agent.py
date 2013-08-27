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
import copy

from zope.interface import implements

from feat.agents.base import agent, partners, replay
from feat.agents.base import dependency, problem, task, contractor, requester
from feat.agents.base import sender
from feat.agents.common import host, rpc, shard, monitor, start_agent
from feat.agents.monitor import intensive_care, clerk, simulation
from feat.database import document
from feat.common import fiber, serialization, defer, time, manhole, text_helper
from feat.agents.application import feat
from feat import applications

from feat.agents.monitor.interface import DEFAULT_HEARTBEAT_PERIOD
from feat.agents.monitor.interface import DEFAULT_DEATH_SKIPS
from feat.agents.monitor.interface import DEFAULT_CONTROL_PERIOD
from feat.agents.monitor.interface import DEFAULT_NOTIFICATION_PERIOD
from feat.agents.monitor.interface import DEFAULT_HOST_QUARANTINE_LENGTH
from feat.agents.monitor.interface import DEFAULT_DYING_SKIPS
from feat.agents.monitor.interface import DEFAULT_SELF_QUARANTINE_LENGTH
from feat.agents.monitor.interface import IAssistant, ICoroner, RestartStrategy
from feat.agents.monitor.interface import IIntensiveCareFactory, IClerkFactory
from feat.agents.monitor.interface import RestartFailed
from feat.interface.agent import IMonitorAgent
from feat.interface.agency import ExecMode
from feat.interface.protocols import ProtocolFailed
from feat.interface.recipient import IRecipient


DEFAULT_NEIGHBOURS_CHECK_PERIOD = 120


@feat.register_restorator
class MonitoredPartner(agent.BasePartner):

    instance_id = 0
    location = "unknown"
    type_name = "unknown"
    agent_type = "unknown"

    type_name = 'monitor->agent'

    def __init__(self, *args, **kwargs):
        partners.BasePartner.__init__(self, *args, **kwargs)
        self.instance_id = None

    def initiate(self, agent):
        f = self._update_monitoring_info(agent)
        f.add_callback(agent.add_monitored)
        return f

    def on_goodbye(self, agent):
        agent.remove_monitored(self)

    def on_breakup(self, agent):
        agent.remove_monitored(self)

    def on_died(self, agent):
        agent.remove_monitored(self)

    def on_buried(self, agent):
        agent.remove_monitored(self)

    def on_restarted(self, agent, old_recipient):
        f = self._update_monitoring_info(agent)
        f.add_callback(agent.update_monitored, old_recipient)
        return f

    def _update_monitoring_info(self, agent):
        f = agent.query_monitoring_info(self.recipient)
        f.add_callbacks(self._monitoring_info_changed,
                        self._no_monitoring_info)
        return f

    def _monitoring_info_changed(self, info):
        self.instance_id = info.instance_id
        self.location = info.location
        self.agent_type = info.agent_type
        return self

    def _no_monitoring_info(self, _failure):
        # Ignoring the error, going on with default values
        return self


@feat.register_restorator
class MonitorPartner(monitor.PartnerMixin, MonitoredPartner):

    type_name = 'monitor->monitor'


@feat.register_restorator
class ForeignShardPartner(MonitoredPartner):

    type_name = 'monitor->foreign_shard'


@feat.register_restorator
class ShardPartner(MonitoredPartner):

    type_name = 'monitor->shard'

    def initiate(self, agent):
        agent.call_next(agent.update_neighbour_monitors,
                        shard_recip=self.recipient)


@feat.register_restorator
class HostPartner(MonitoredPartner, agent.HostPartner):

    type_name = 'monitor->host'


class Partners(agent.Partners):

    #FIXME: Only partners with role "monitored" should use MonitoredPartner
    default_handler = MonitoredPartner
    default_role = u'monitor'

    partners.has_one('shard', 'shard_agent', ShardPartner)
    partners.has_many('foreign_shards', 'shard_agent',
                      ForeignShardPartner, role="foreigner")
    partners.has_many('monitors', 'monitor_agent', MonitorPartner, "monitor")
    # overwrite the definition from agent.Partners, so that host agents
    # are properly monitored
    partners.has_many('hosts', 'host_agent', HostPartner)


@feat.register_restorator
class MonitorAgentConfiguration(document.Document):

    type_name = 'monitor_agent_conf'
    document.field('doc_id', u'monitor_agent_conf', '_id')
    document.field('heartbeat_period', DEFAULT_HEARTBEAT_PERIOD)
    document.field('heartbeat_death_skips', DEFAULT_DEATH_SKIPS)
    document.field('heartbeat_dying_skips', DEFAULT_DYING_SKIPS)
    document.field('control_period', DEFAULT_CONTROL_PERIOD)
    document.field('notification_period', DEFAULT_NOTIFICATION_PERIOD)
    document.field('enable_quarantine', True)
    document.field('host_quarantine_length', DEFAULT_HOST_QUARANTINE_LENGTH)
    document.field('self_quarantine_length', DEFAULT_SELF_QUARANTINE_LENGTH)
    document.field('neighbours_check_period', DEFAULT_NEIGHBOURS_CHECK_PERIOD)


feat.initial_data(MonitorAgentConfiguration)


Descriptor = monitor.Descriptor


@feat.register_agent('monitor_agent')
class MonitorAgent(agent.BaseAgent, sender.AgentMixin,
                   host.SpecialHostPartnerMixin):

    implements(shard.IShardNotificationHandler, IAssistant, ICoroner,
               IMonitorAgent)

    partners_class = Partners

    restart_strategy = RestartStrategy.monitor

    dependency.register(IIntensiveCareFactory, intensive_care.IntensiveCare,
                        ExecMode.production)
    dependency.register(IIntensiveCareFactory, simulation.IntensiveCare,
                        ExecMode.test)
    dependency.register(IIntensiveCareFactory, simulation.IntensiveCare,
                        ExecMode.simulation)

    dependency.register(IClerkFactory, clerk.Clerk,
                        ExecMode.production)
    dependency.register(IClerkFactory, simulation.Clerk,
                        ExecMode.test)
    dependency.register(IClerkFactory, simulation.Clerk,
                        ExecMode.simulation)

    need_local_monitoring = False # We handle monitors on our own

    @replay.mutable
    def initiate(self, state):
        self._paused = False

        shard.register_for_notifications(self)

        solver = problem.SolveProblemInterest(DeadAgent())
        service = contractor.Service("monitoring")
        state.medium.register_interest(solver)
        state.medium.register_interest(service)

        config = state.medium.get_configuration()
        control_period = config.control_period
        enable_quarantine = config.enable_quarantine
        host_quarantine = config.host_quarantine_length
        self_quarantine = config.self_quarantine_length

        state.updating_neighbours = False
        state.need_neighbour_update = False

        state.clerk = self.dependency(IClerkFactory, self, self,
                                      location=state.medium.get_hostname(),
                                      enable_quarantine=enable_quarantine,
                                      host_quarantine_length=host_quarantine,
                                      self_quarantine_length=self_quarantine)
        state.intensive_care = self.dependency(IIntensiveCareFactory,
                                               self, state.clerk,
                                               control_period=control_period)

        # agent_id -> HandleDeath instance
        state.handler_tasks = dict()

    @replay.mutable
    def startup(self, state):
        state.clerk.startup()
        state.intensive_care.startup()
        config = state.medium.get_configuration()
        state.medium.initiate_protocol(CheckNeighboursTask,
                                       config.neighbours_check_period)
        if not state.medium.is_connected():
            state.clerk.on_disconnected()

    @replay.journaled
    def on_disconnect(self, state):
        state.clerk.on_disconnected()

    @replay.journaled
    def on_reconnect(self, state):
        state.clerk.on_reconnected()

    ### ICoroner ###

    def on_patient_dead(self, patient):
        self.info("Agent %s is not responding, handle its death",
                  patient.recipient.key)
        self.handle_agent_death(patient.recipient)

    @manhole.expose()
    @replay.immutable
    def show_monitoring_status(self, state):

        def patients(patients):
            tab = text_helper.Table(
                    fields=('agent_id', 'shard', 'state', 'counter'),
                    lengths=(37, 37, 7, 9))
            return tab.render((v.recipient.key, v.recipient.route,
                               v['state'].name, v['counter'])
                              for _k, v in patients.iteritems())

        def locations(locations):
            tab = text_helper.Table(
                    fields=('location', 'state', 'patients', ),
                    lengths=(58, 12, 90))
            return tab.render((k, v["state"].name, patients(v["patients"]))
                              for k, v in locations.iteritems())

        status = self.get_monitoring_status()
        return locations(status["locations"])

    @manhole.expose()
    @replay.immutable
    def get_monitoring_status(self, state):
        locations = {}
        result = {"state": state.clerk.state,
                  "location": state.clerk.location,
                  "locations": locations}

        for loc in state.clerk.iter_locations():
            patients = {}
            location = {"state": loc.state,
                        "patients": patients}
            locations[loc.name] = location

            for pat in loc.iter_patients():
                patient = {"state": pat.state,
                           "patient_type": pat.patient_type,
                           "recipient": pat.recipient,
                           "counter": pat.counter}
                patients[pat.recipient.key] = patient

        return result

    @manhole.expose()
    @replay.immutable
    def pause(self, state):
        self.debug("Pausing agent monitoring")
        state.intensive_care.pause()

    @manhole.expose()
    @replay.immutable
    def resume(self, state):
        self.debug("Resuming agent monitoring")
        state.intensive_care.resume()

    @replay.mutable
    def handle_agent_death(self, state, recp):
        recp = IRecipient(recp)
        task = state.handler_tasks.get(recp.key, None)
        if task:
            return task.notify_finish()
        else:
            task = self.initiate_protocol(HandleDeath, recp,
                                          state.notification_sender)
            self._register_task(recp.key, task)
            return task.notify_finish()

    @replay.mutable
    def _register_task(self, state, agent_id, task):
        if agent_id in state.handler_tasks:
            self.error('Tried to register task which we already have.')
        else:
            state.handler_tasks[agent_id] = task

    @replay.mutable
    def _unregister_task(self, state, agent_id):
        task = state.handler_tasks.pop(agent_id, None)
        if task is None or not task.finished():
            self.warning('In _unregister_task(). Expected to get the '
                         'finished task instance, got %r instead.', task)

    @rpc.publish
    @replay.mutable
    def restart_complete(self, state, recp):
        '''
        Called by agents who accepted responsability of restarting some other
        agent, to notify us that the job is done.
        '''
        recp = IRecipient(recp)
        task = state.handler_tasks.get(recp.key, None)
        if task:
            self.call_next(task.restart_complete, recp)
        else:
            self.warning('Received notification about the finished restart '
                         'of the agent %r, but no handler task for this agent '
                         'has been found.', recp)

    @rpc.publish
    @replay.mutable
    def restart_handeled(self, state, agent_id):
        '''
        Called by other monitor agent to notify us, that the restart of
        agent[id=agent_id] has been completed. This lets us terminate our
        HandleDeath task ask this is no longer needed.
        '''
        task = state.handler_tasks.get(agent_id, None)
        if task:
            task.restart_handeled()
        else:
            self.warning("Received restart_handled but didn't found a "
                         "matching task. Agent_id: %r.", agent_id)

    @replay.mutable
    def handling_death_requested(self, state, agent_id, instance_id):
        '''
        I get called when some other monitoring agent demands me to fix the
        problem of the dead agent.
        '''
        task = state.handler_tasks.get(agent_id, None)
        if task:
            # we already know about this death, just return the IProblem
            return task
        else:
            # we don't yet know about the death or we have already solved it
            # we need to check the instance_id to know which is the case
            partner = self.find_partner(agent_id)
            if not partner:
                return fiber.fail(partners.FindPartnerError(
                    "I have been requested to solve the death of the agent %r"
                    "which I'm not monitoring. This is weird!" % (agent_id, )))
            if partner.instance_id == instance_id:
                # we didn't know, lets handle it
                task = self.initiate_protocol(HandleDeath, partner.recipient,
                                              state.notification_sender)
                self._register_task(agent_id, task)
                return task
            else:
                # already solved
                return AlreadySolvedDeath(self, partner.recipient.key)

    def on_new_neighbour_shard(self, recipient):
        #FIXME: We shouldn't do a full update in this case
        return self.update_neighbour_monitors()

    def on_neighbour_shard_gone(self, recipient):
        #FIXME: We shouldn't do a full update in this case
        return self.update_neighbour_monitors()

    @manhole.expose()
    @replay.mutable
    def update_neighbour_monitors(self, state, shard_recip=None):
        if state.updating_neighbours:
            state.need_neighbour_update = True
            return self
        state.updating_neighbours = True
        state.need_neighbour_update = False

        f = self._get_monitors(shard_recip=shard_recip)
        f.add_callback(self._update_monitors)
        f.add_callback(fiber.override_result, self)
        f.add_both(self.neighbour_monitors_updated)
        return f

    @replay.mutable
    def neighbour_monitors_updated(self, state, param):
        state.updating_neighbours = False
        if state.need_neighbour_update:
            return self.update_neighbour_monitors()
        return param

    def _get_monitors(self, shard_recip=None):
        return shard.query_structure(self, 'monitor_agent',
                                     shard_recip=shard_recip, distance=1)

    @replay.mutable
    def _update_monitors(self, state, monitors):
        myself = IRecipient(self)
        recipients = set([IRecipient(m) for m in monitors
                          if IRecipient(m) != myself])
        currents = set([p.recipient for p in state.partners.monitors])

        old = currents - recipients
        new = recipients - currents

        fibers = []
        for monitor in new:
            fibers.append(self._add_monitor_partner(monitor))
        for monitor in old:
            fibers.append(self._remove_monitor_partner(monitor))

        return fiber.FiberList(filter(None, fibers)).succeed()

    def _add_monitor_partner(self, recipient):
        ourself = self.get_own_address()
        if ourself.key > recipient.key:
            # We have the bigger one
            self.debug("Partnering with new monitor %s", recipient)
            return self.establish_partnership(recipient)
        #FIXME: Maybe we should schedule a check to force partnership ?
        self.debug("Waiting for monitor %s to propose", recipient)

    @replay.immutable
    def _remove_monitor_partner(self, state, recipient):
        ourself = self.get_own_address()
        if ourself.key > recipient.key:
            # We have the bigger one
            self.debug("Breaking up with old monitor %s", recipient)
            return self.breakup(recipient)
        #FIXME: Maybe we should schedule a check to force breakup ?
        self.debug("Waiting for old monitor %s to breakup", recipient)

    ### protected ###

    @replay.mutable
    def add_monitored(self, state, partner):
        #FIXME: Add location query
        if state.intensive_care.has_patient(partner.recipient):
            return
        config = state.medium.get_configuration()
        period = config.heartbeat_period
        dying_skips = config.heartbeat_dying_skips
        death_skips = config.heartbeat_death_skips

        state.intensive_care.add_patient(partner.recipient,
                                         partner.location,
                                         period=period,
                                         dying_skips=dying_skips,
                                         death_skips=death_skips,
                                         patient_type=partner.agent_type)

    @replay.mutable
    def update_monitored(self, state, partner, old_recipient):
        #FIXME: Add location query and update
        if old_recipient and state.intensive_care.has_patient(old_recipient):
            state.intensive_care.remove_patient(old_recipient)

        self.add_monitored(partner)

    @replay.mutable
    def remove_monitored(self, state, partner):
        state.intensive_care.remove_patient(partner.recipient)


@feat.register_restorator
class AlreadySolvedDeath(problem.BaseProblem):

    def __init__(self, agent, solution):
        self.agent = agent
        self.solution = solution

    def wait_for_solution(self):
        return fiber.succeed(self.solution)

    def solve_for(self, solution, recp):
        return self.agent.call_remote(recp, 'restart_handeled', solution)


@feat.register_restorator
class DeadAgent(serialization.Serializable):
    implements(problem.IProblemFactory)

    problem_id = 'dead-agent'

    def __call__(self, agent, agent_id, instance_id):
        return agent.handling_death_requested(
            agent_id, instance_id)


class HandleDeath(task.BaseTask):
    implements(problem.IProblem)

    problem_id = 'dead-agent'

    protocol_id = 'tash:monitor.handle-death'

    # timeout for this task is dynamic
    timeout = None

    @replay.entry_point
    def initiate(self, state, recp, sender):
        state.recp = recp
        state.descriptor = None
        state.factory = None
        state.attempt = 0
        state.timeout_call_id = None
        state.monitors = None
        # NotificationSender task
        state.sender = sender

        self._init_ouside()

        state.agent.call_next(self._bind_unregistering_self)

        f = self._fetch_descriptor()
        f.add_callback(fiber.drop_param, self._determine_factory)
        f.add_callback(fiber.drop_param, self._start_collective_solver)
        return f

    @replay.entry_point
    def restart_complete(self, state, new_address):
        '''
        Called when we get notified that the restart has been completed by
        some agent who has volontureed to do so.
        '''
        if state.timeout_call_id:
            state.agent.cancel_delayed_call(state.timeout_call_id)
            state.timeout_call_id = None
        return self._send_restarted_notifications(new_address)

    @replay.mutable
    def restart_handeled(self, state):
        state.medium.terminate()

    @replay.mutable
    def _start_collective_solver(self, state):
        '''
        Determines who from all the monitors monitoring this agent should
        resolve the issue.
        '''
        own_address = state.agent.get_own_address()
        monitors = [IRecipient(x) for x in state.descriptor.partners
                    if x.role == u'monitor']
        im_included = any([x == own_address for x in monitors])
        if not im_included:
            monitors.append(own_address)
        # this object is going to be stored in the state of CollectiveSolver,
        # we need to deepcopy it not to share a refrence
        state.monitors = copy.deepcopy(monitors)
        state.agent.initiate_protocol(problem.CollectiveSolver,
                                      self, monitors)
        return task.NOT_DONE_YET

    ### IProblem ###

    @replay.immutable
    def get_keywords(self, state):
        res = {'instance_id': state.descriptor.instance_id,
               'agent_id': state.descriptor.doc_id}
        return res

    @replay.immutable
    def wait_for_solution(self, state):
        return self.notify_finish()

    @replay.immutable
    def solve_for(self, state, solution, recp):
        return state.agent.call_remote(recp, 'restart_handeled',
                                       state.descriptor.doc_id)

    @replay.journaled
    def solve_localy(self, state):
        f = self._retry()
        f.add_callback(self._wait_handled)
        f.add_both(state.medium.terminate)
        f.add_callback(fiber.override_result, self)
        return f

    ### endof IProblem ###

    @replay.mutable
    def _retry(self, state):
        '''
        Starts a single try of the whole restart path.
        '''
        state.attempt += 1
        self.debug('Starting restart attempt: %d.', state.attempt)
        if self._cmp_strategy(RestartStrategy.buryme):
            self.debug('Agent %r is going to by buried according to his '
                       'last will.', state.factory.descriptor_type)
            return self._send_buried_notifications()
        else:
            f = self._set_restart_flag()
            f.add_callback(fiber.drop_param, self._send_died_notifications)
            f.add_both(self._ensure_someone_took_responsability)
            return f

    @replay.mutable
    def _set_restart_flag(self, state):
        state.descriptor.under_restart = True
        state.so_took_responsability = False
        f = state.agent.save_document(state.descriptor)
        f.add_callback(self._store_descriptor)
        return f

    @replay.mutable
    def _send_died_notifications(self, state):
        self.log("Sending 'died' notifications to the partners, which are: %r",
                 state.descriptor.partners)

        fibers = list()
        for partner, brothers in self._iter_categorized_partners():
            f = requester.notify_died(
                state.agent, partner, state.recp, brothers)
            f.add_callback(self._on_died_response_handler)
            fibers.append(f)
        f = fiber.FiberList(fibers, consumeErrors=True)
        f.succeed()
        return f

    @replay.mutable
    def _send_buried_notifications(self, state):
        self.log("Sending 'buried' notifications to the partners, "
                 "which are: %r", state.descriptor.partners)
        notifications = list()
        for partner, brothers in self._iter_categorized_partners():
            notification = sender.PendingNotification(
                recipient=IRecipient(partner),
                type='buried',
                origin=state.recp,
                payload=brothers)
            notifications.append(notification)

        f = state.sender.notify(notifications)
        f.add_both(fiber.drop_param, state.agent.delete_document,
                   state.descriptor)
        f.add_both(fiber.drop_param, self._death_handled, None)
        return f

    @replay.mutable
    def _send_restarted_notifications(self, state, new_address):
        self.log("Sending 'restarted' notifications to the partners, "
                 "which are: %r", state.descriptor.partners)
        notifications = list()
        for partner in state.descriptor.partners:
            notifications.append(sender.PendingNotification(
                recipient=IRecipient(partner),
                type='restarted',
                origin=state.recp,
                payload=new_address))
        f = state.sender.notify(notifications)
        f.add_both(fiber.drop_param, self._death_handled, new_address)
        return f

    @replay.mutable
    def _on_died_response_handler(self, state, response):
        if state.so_took_responsability:
            self.log('Someone already took responsability, ignoring.')
            return
        if isinstance(response, partners.ResponsabilityAccepted):
            state.so_took_responsability = True
            time_left = self._time_left(response.expiration_time)
            state.timeout_call_id = state.agent.call_later(
                time_left, self._timeout_waiting_for_restart)

    @replay.side_effect
    def _time_left(self, moment):
        return time.left(moment)

    @replay.mutable
    def _ensure_someone_took_responsability(self, state, _responses):
        '''
        Called as a callback for sending *died* notifications to all the
        partners.
        Check if someone has offered to restart the agent.
        If yes, setup expiration call and wait for report.
        If no, initiate doing it on our own.
        '''
        if not state.so_took_responsability:
            self.debug('Noone took responsability, I will try to restart '
                       '%r agent myself', state.factory.descriptor_type)
            return self._restart_yourself()

    def _timeout_waiting_for_restart(self):
        self.error("Timeout waiting for the responsable agent to send the "
                   "notification. I will retry the whole procedure.")
        return self._retry()

    @replay.mutable
    def _restart_yourself(self, state):
        f = fiber.succeed()
        f.add_callback(fiber.drop_param,
                       host.start_agent_in_shard,
                       state.agent, state.descriptor, state.descriptor.shard)
        f.add_callbacks(self._send_restarted_notifications,
                        self._local_restart_failed)
        return f

    @replay.immutable
    def _local_restart_failed(self, state, fail):
        '''
        Getting here means that all the host agents in the shard are gone.
        Depending on the restart strategy we finish here, migrate out of the
        shard or take over (monitoring agent).
        '''
        self.info('Restarting of %r in the same shard failed.',
                  state.descriptor.type_name)
        if self._cmp_strategy(RestartStrategy.local):
            self.info('Giving up, just sending buried notifications.')
            f = self._send_buried_notifications()
            f.add_callback(fiber.drop_param, state.medium.terminate, None)
            return f
        elif self._cmp_strategy(RestartStrategy.wherever):
            self.info('Trying to find an allocation anywhere in the cluster.')
            # first we need to clear the host partner, it is necessary, because
            # agent will bind to different exchange after the restart, so
            # he will never receive the notification
            # about burring his previous host
            f = self._clear_host_partner()
            f.add_callback(fiber.inject_param, 2,
                           state.agent.initiate_protocol,
                           start_agent.GloballyStartAgent)
            f.add_callback(fiber.call_param, 'notify_finish')
            # GloballyStartAgent task is updating descriptor, to get things
            # we need to redownload it here
            f.add_callback(fiber.bridge_param, self._fetch_descriptor)
            f.add_callbacks(self._send_restarted_notifications,
                            self._global_restart_failed)
            return f
        elif self._cmp_strategy(RestartStrategy.monitor):
            self.info('Taking over the role of the died monitor.')
            f = self._send_buried_notifications()
            f.add_callback(fiber.drop_param, self._checkup_partners)
            f.add_callback(fiber.drop_param, self._adopt_notifications)
            f.add_callback(fiber.drop_param, state.medium.terminate, None)
            return f
        else:
            state.medium.fail(RestartFailed('Unknown restart strategy: %r' %
                                            (self.factory.restart_strategy, )))

    @replay.immutable
    def _global_restart_failed(self, state, fail):
        fail.trap(ProtocolFailed)
        msg = ("Chaos monkey won this time! GloballyStartAgent task returned"
               " failure. Just sending buried notifications for %r." %
               state.descriptor.type_name)
        exp = RestartFailed(msg)
        f = fiber.succeed()
        f.add_callback(fiber.drop_param, self._send_buried_notifications)
        f.add_callback(fiber.drop_param, state.medium.fail, exp)
        return f

    @replay.journaled
    def _checkup_partners(self, state):
        self.debug('Checking up on the partners, which are: %r',
                   state.descriptor.partners)
        fibers = list()
        agent_id = state.agent.get_agent_id()
        for partner in state.descriptor.partners:
            if partner.recipient.key == agent_id:
                # We don't want to monitor ourself
                continue
            f = requester.ping(state.agent, partner)
            f.add_callbacks(self._ping_success, self._ping_failed,
                            cbargs=(partner, ), ebargs=(partner, ))
            fibers.append(f)
        f = fiber.FiberList(fibers, consumeErrors=True)
        return f.succeed()

    @replay.journaled
    def _adopt_notifications(self, state):
        '''Part of the "monitor" restart strategy. The pending notifications
        from descriptor of dead agent are imported to our pending list.'''

        def iterator():
            it = state.descriptor.pending_notifications.iteritems()
            for _, nots in it:
                for x in nots:
                    yield x

        to_adopt = list(iterator())
        self.info("Will adopt %d pending notifications.", len(to_adopt))
        return state.sender.notify(to_adopt)

    @replay.immutable
    def _ping_failed(self, state, fail, partner):
        self.debug('Sending ping to the partner %r failed with %r. '
                   'Initializing death handling task.', partner, fail)
        return state.agent.handle_agent_death(partner)

    @replay.immutable
    def _ping_success(self, state, _, partner):
        self.debug('Sending ping to the partner %r was successful. '
                   'Taking over the role of the monitor.', partner)
        return state.agent.establish_partnership(partner,
                                                 partner_role="foreigner")

    @replay.mutable
    def _clear_host_partner(self, state):
        f = state.descriptor.remove_host_partner(state.agent)
        f.add_callback(self._store_descriptor)
        return f

    @replay.mutable
    def _fetch_descriptor(self, state):
        f = state.agent.get_document(state.recp.key)
        f.add_callback(self._store_descriptor)
        return f

    @replay.mutable
    def _store_descriptor(self, state, desc):
        state.descriptor = desc
        return desc

    @replay.mutable
    def _determine_factory(self, state):
        state.factory = applications.lookup_agent(state.descriptor.type_name)

    @replay.immutable
    def _cmp_strategy(self, state, strategy):
        return state.factory.restart_strategy == strategy

    @replay.immutable
    def _iter_categorized_partners(self, state):
        '''
        Iterator over the partners giving as extra param partners of the same
        category.
        '''
        # categorize partners into the structure
        # partner_class -> list of its instances
        categorized = dict()
        for partner in state.descriptor.partners:
            category, index = categorized.get(partner.__class__,
                                              (list(), len(categorized)))
            category.append(partner)
            categorized[partner.__class__] = tuple([category, index])

        for category, (brothers, index) in sorted(categorized.items(),
                                                  key=lambda x: x[1][1]):
            for partner in brothers:
                yield partner, brothers

    @replay.immutable
    def _bind_unregistering_self(self, state):
        d = self.notify_finish()
        d.addCallback(defer.drop_param,
                      state.agent._unregister_task,
                      state.recp.key)
        return d

    @replay.side_effect
    def _init_ouside(self):
        self._handled = defer.Deferred()
        self._result = None

    @replay.side_effect
    def _death_handled(self, result):
        if self._handled is not None:
            self._handled.callback(result)
            self._result = result
            self._handled = None

    def _wait_handled(self, _):
        if self._handled is not None:
            return self._handled
        return self._result


class CheckNeighboursTask(task.StealthPeriodicTask):

    protocol_id = "monitor:check-neighbours"

    @replay.immutable
    def run(self, state):
        neighbours = state.agent.query_partners(MonitorPartner)
        if not neighbours:
            return state.agent.update_neighbour_monitors()
