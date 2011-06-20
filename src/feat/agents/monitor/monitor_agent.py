# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from zope.interface import implements

import copy

from feat.agents.base import agent, partners, document, replay
from feat.agents.base import dependency, problem, task, contractor, requester
from feat.agents.base import dbtools
from feat.agents.common import raage, host, rpc, shard, monitor
from feat.agents.monitor import intensive_care, clerk, simulation
from feat.common import fiber, serialization, defer, time
from feat.common import error, manhole, text_helper

from feat.agents.monitor.interface import *
from feat.interface.agency import *
from feat.interface.protocols import *
from feat.interface.recipient import *
from feat.agencies.interface import NotFoundError


@serialization.register
class MonitoredPartner(agent.BasePartner):

    type_name = 'monitor->agent'

    def __init__(self, *args, **kwargs):
        partners.BasePartner.__init__(self, *args, **kwargs)
        self.instance_id = None

    def initiate(self, agent):
        f = self._update_instance_id(agent)
        f.add_callback(fiber.drop_param, agent.add_monitored, self)
        return f

    def on_goodbye(self, agent, _payload):
        agent.remove_monitored(self)

    def on_breakup(self, agent):
        agent.remove_monitored(self)

    def on_died(self, agent, _payload, _monitor):
        agent.remove_monitored(self)

    def on_buried(self, agent, _payload):
        agent.remove_monitored(self)

    def on_restarted(self, agent, old_recipient):
        f = self._update_instance_id(agent)
        f.add_callback(fiber.drop_param,
                       agent.update_monitored, self, old_recipient)
        return f

    def _update_instance_id(self, agent):
        f = agent.get_document(self.recipient.key)
        f.add_callback(self._instance_id_changed, agent)
        return f

    def _instance_id_changed(self, doc, agent):
        self.instance_id = doc.instance_id


@serialization.register
class MonitorPartner(monitor.PartnerMixin, MonitoredPartner):

    type_name = 'monitor->monitor'

    def initiate(self, agent):
        f = fiber.succeed()
        f.add_callback(fiber.drop_param,
                       MonitoredPartner.initiate, self, agent)
        f.add_callback(fiber.drop_param,
                       monitor.PartnerMixin.initiate, self, agent)
        return f

    def on_goodbye(self, agent, brothers):
        d = defer.succeed(None)
        d.addCallback(defer.drop_param,
                      monitor.PartnerMixin.on_goodbye, self, agent, brothers)
        d.addCallback(defer.drop_param,
                      MonitoredPartner.on_goodbye, self, agent, brothers)
        return d

    def on_buried(self, agent, brothers):
        d = defer.succeed(None)
        d.addCallback(defer.drop_param,
                      monitor.PartnerMixin.on_buried, self, agent, brothers)
        d.addCallback(defer.drop_param,
                      MonitoredPartner.on_buried, self, agent, brothers)
        return d


@serialization.register
class ForeignShardPartner(MonitoredPartner):

    type_name = 'monitor->foreign_shard'


@serialization.register
class ShardPartner(MonitoredPartner):

    type_name = 'monitor->shard'

    def initiate(self, agent):
        f = MonitoredPartner.initiate(self, agent)
        f.add_callback(fiber.drop_param, agent.call_next,
                       agent.update_neighbour_monitors)
        return f


class Partners(agent.Partners):

    #FIXME: Only partners with role "monitored" should use MonitoredPartner
    default_handler = MonitoredPartner
    default_role = u'monitor'

    partners.has_one('shard', 'shard_agent', ShardPartner)
    partners.has_many('foreign_shards', 'shard_agent',
                      ForeignShardPartner, role="foreigner")
    partners.has_many('monitors', 'monitor_agent', MonitorPartner, "monitor")


@document.register
class MonitorAgentConfiguration(document.Document):

    document_type = 'monitor_agent_conf'
    document.field('doc_id', u'monitor_agent_conf', '_id')
    document.field('heartbeat_period', DEFAULT_HEARTBEAT_PERIOD)
    document.field('heartbeat_death_skips', DEFAULT_DEATH_SKIPS)
    document.field('heartbeat_dying_skips', DEFAULT_DYING_SKIPS)
    document.field('control_period', DEFAULT_CONTROL_PERIOD)
    document.field('notification_period', DEFAULT_NOTIFICATION_PERIOD)


dbtools.initial_data(MonitorAgentConfiguration)


Descriptor = monitor.Descriptor
PendingNotification = monitor.PendingNotification


@agent.register('monitor_agent')
class MonitorAgent(agent.BaseAgent, rpc.AgentMixin):

    implements(shard.IShardNotificationHandler, IAssistant, ICoroner)

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

        state.clerk = self.dependency(IClerkFactory, self, self)
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
        period = config.notification_period
        proto = state.medium.initiate_protocol(NotificationSender,
                                               clerk=state.clerk,
                                               period=period)
        state.notification_sender = proto

    ### ICoroner ###

    def on_patient_dead(self, patient):
        self.info("Agent %s is not responding, handle its death",
                  patient.recipient.key)
        self.handle_agent_death(patient.recipient)

    @manhole.expose()
    @replay.immutable
    def show_status(self, state):
        tab = text_helper.Table(
            fields=('agent_id', 'shard', 'counter', 'state', ),
            lengths=(35, 45, 15, 20, ))
        iterator = self.get_monitoring_status().iteritems()
        return tab.render((k.key, k.shard, v['counter'], v['state'].name, )
                           for k, v in iterator)

    @manhole.expose()
    @replay.immutable
    def get_monitoring_status(self, state):
        result = {}
        for patient in state.intensive_care.iter_patients():
            result[patient.recipient] = {"state": patient.state,
                                         "counter": patient.counter}
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

    @replay.mutable
    def update_neighbour_monitors(self, state):
        f = self._get_monitors()
        f.add_callback(self._update_monitors)
        return f

    def _get_monitors(self):
        return shard.query_structure(self, 'monitor_agent', distance=1)

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
        return fiber.FiberList(fibers).succeed()

    def _add_monitor_partner(self, recipient):
        self.debug("Partnering with new monitor %s", recipient)
        return self.establish_partnership(recipient)

    @replay.immutable
    def _remove_monitor_partner(self, state, recipient):
        self.debug("Leaving old monitor %s", recipient)
        return self.breakup(recipient)

    @replay.immutable
    def has_empty_outbox(self, state):
        return state.notification_sender.has_empty_outbox()

    ### protected ###

    @replay.mutable
    def add_monitored(self, state, partner):
        #FIXME: Add location query
        config = state.medium.get_configuration()
        period = config.heartbeat_period
        dying_skips = config.heartbeat_dying_skips
        death_skips = config.heartbeat_death_skips

        state.intensive_care.add_patient(partner.recipient, None,
                                         period=period,
                                         dying_skips=dying_skips,
                                         death_skips=death_skips)

    @replay.mutable
    def update_monitored(self, state, partner, old_recipient):
        #FIXME: Add location query and update
        if old_recipient and state.intensive_care.has_patient(old_recipient):
            state.intensive_care.remove_patient(old_recipient)

        if not state.intensive_care.has_patient(partner.recipient):
            self.add_monitored(partner)
            return

    @replay.mutable
    def remove_monitored(self, state, partner):
        state.intensive_care.remove_patient(partner.recipient)


@serialization.register
class AlreadySolvedDeath(problem.BaseProblem):

    def __init__(self, agent, solution):
        self.agent = agent
        self.solution = solution

    def wait_for_solution(self):
        return fiber.succeed(self.solution)

    def solve_for(self, solution, recp):
        return self.agent.call_remote(recp, 'restart_handeled', solution)


@serialization.register
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

        f = state.agent.get_document(state.recp.key)
        f.add_callback(self._store_descriptor)
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
        f.add_both(self.debug_mark)
        f.add_both(state.medium.terminate)
        f.add_callback(fiber.override_result, self)
        return f

    @replay.journaled
    def debug_mark(self, state, param):
        return param

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
            f = self._send_died_notifications()
            f.add_both(self._ensure_someone_took_responsability)
            return f

    @replay.mutable
    def _send_died_notifications(self, state):
        self.log("Sending 'died' notifications to the partners, which are: %r",
                 state.descriptor.partners)
        state.so_took_reponsability = False
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
            notification = monitor.PendingNotification(
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
            notifications.append(monitor.PendingNotification(
                                             recipient=IRecipient(partner),
                                             type='restarted',
                                             origin=state.recp,
                                             payload=new_address))
        f = state.sender.notify(notifications)
        f.add_both(fiber.drop_param, self._death_handled, new_address)
        return f

    @replay.mutable
    def _on_died_response_handler(self, state, response):
        if state.so_took_reponsability:
            self.log('Someone already took responsability, ignoring.')
            return
        if isinstance(response, partners.ResponsabilityAccepted):
            state.so_took_reponsability = True
            time_left = time.left(response.expiration_time)
            state.timeout_call_id = state.agent.call_later(
                time_left, self._timeout_waiting_for_restart)

    @replay.mutable
    def _ensure_someone_took_responsability(self, state, _responses):
        '''
        Called as a callback for sending *died* notifications to all the
        partners.
        Check if someone has offered to restart the agent.
        If yes, setup expiration call and wait for report.
        If no, initiate doing it on our own.
        '''
        if not state.so_took_reponsability:
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
                  state.descriptor.document_type)
        if self._cmp_strategy(RestartStrategy.local):
            self.info('Giving up, just sending buried notifications.')
            f = self._send_buried_notifications()
            f.add_callback(fiber.drop_param, state.medium.terminate, None)
            return f
        elif self._cmp_strategy(RestartStrategy.wherever):
            self.info('Trying to find an allocation anywhere in the cluster.')
            # first we need to clear the host partner, it is necessary, because
            # agent will bind to different exchange after the restart, so
            # he will never receive the notification about burring his previous
            # host
            f = self._clear_host_partner()
            f.add_callback(fiber.drop_param, raage.retrying_allocate_resource,
                state.agent, resources=state.factory.resources,
                categories=state.factory.categories, max_retries=3)
            f.add_callback(self._request_starting_agent)
            f.add_callback(self._send_restarted_notifications)
            f.add_errback(self._finding_allocation_failed)
            return f
        elif self._cmp_strategy(RestartStrategy.monitor):
            self.info('Taking over the role of the died monitor.')
            f = self._checkup_partners()
            f.add_callback(fiber.drop_param,
                           self._adopt_notifications)
            f.add_callback(fiber.drop_param,
                           self._send_buried_notifications)
            f.add_callback(fiber.drop_param, state.medium.terminate, None)
            return f
        else:
            state.medium.fail(RestartFailed('Unknown restart strategy: %r' %
                                            (self.factory.restart_strategy, )))

    @replay.immutable
    def _finding_allocation_failed(self, state, fail):
        fail.trap(ProtocolFailed)
        msg = ("Chaos monkey won this time! Despite 3 times trying we "
               "failed to find the allocation for the the %r. "
               "Just sending buried notifications." %
               state.descriptor.document_type)
        exp = RestartFailed(msg)
        f = self._send_buried_notifications()
        f.add_callback(fiber.drop_param, state.medium.fail, exp)
        return f

    @replay.mutable
    def _request_starting_agent(self, state, (allocation_id, recp)):
        # we are setting shard=None here first, because of the logic in
        # Host Agent which prevents it from changing the shard field if it
        # has been set to sth meaningfull (not in [None, 'lobby'])
        f = state.descriptor.set_shard(state.agent, None)
        f.add_callback(self._store_descriptor)
        f.add_callback(fiber.drop_param, host.start_agent,
            state.agent, recp, state.descriptor, allocation_id)
        f.add_errback(self._starting_failed)
        # POSSIBLE FIXME: should we get protected from host agent changing
        # his mind now and not starting the agent?
        # Error handler here could just retry everything.
        return f

    @replay.immutable
    def _starting_failed(self, state, fail):
        self.error("Starting agent failed with: %r, despite the fact "
                   "that getting allocation was successful. "
                   "I will retry the whole procedure.", fail)
        return self._retry()

    @replay.journaled
    def _checkup_partners(self, state):
        self.debug('Checking up on the partners, which are: %r',
                   state.descriptor.partners)
        fibers = list()
        for partner in state.descriptor.partners:
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
    def _store_descriptor(self, state, desc):
        state.descriptor = desc
        return desc

    @replay.mutable
    def _determine_factory(self, state):
        state.factory = agent.registry_lookup(state.descriptor.document_type)
        self.log_name = "HandleDeath %s" % (state.factory.descriptor_type, )

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
            category = categorized.get(partner.__class__, list())
            category.append(partner)
            categorized[partner.__class__] = category

        for category, brothers in categorized.iteritems():
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


class NotificationSender(task.StealthPeriodicTask):

    protocol_id = 'notification-sender'

    @replay.entry_point
    def initiate(self, state, clerk=None, period=None):
        state.clerk = clerk and IClerk(clerk)
        period = period or DEFAULT_NOTIFICATION_PERIOD
        # IRecipient -> list of PendingNotifications
        return task.StealthPeriodicTask.initiate(self, period)

    @replay.immutable
    def run(self, state):
        defers = list()
        for agent_id, notifications in self._iter_outbox():
            if not notifications:
                continue

            if state.clerk and state.clerk.has_patient(agent_id):
                status = state.clerk.get_patient(agent_id)
                if status.state == PatientState.alive:
                    defers.append(self.flush_notifications(agent_id))
            else:
                defers.append(self.flush_notifications(agent_id))
        return defer.DeferredList(defers)

    @replay.mutable
    def flush_notifications(self, state, agent_id):
        return self._flush_next(agent_id)

    @replay.immutable
    def has_empty_outbox(self, state):
        desc = state.agent.get_descriptor()
        if desc.pending_notifications:
            self.log('Pending notifications are: %r',
                     desc.pending_notifications)
            return False
        return True

    ### flushing notifications ###

    @replay.mutable
    def _flush_next(self, state, agent_id):
        notification = self._get_first_pending(agent_id)
        if notification:
            recp = notification.recipient
            f = requester.notify_partner(
                state.agent, recp, notification.type,
                notification.origin, notification.payload)
            f.add_callbacks(fiber.drop_param, self._sending_failed,
                            cbargs=(self._sending_cb, recp, notification, ),
                            ebargs=(recp, ))
            return f

    @replay.mutable
    def _sending_cb(self, state, recp, notification):
        f = self._remove_notification(recp, notification)
        f.add_both(fiber.drop_param, self._flush_next, str(recp.key))
        return f

    @replay.mutable
    def _sending_failed(self, state, fail, recp):
        fail.trap(ProtocolFailed)
        # check that the document still exists, if not it means that this
        # agent got buried

        f = state.agent.get_document(recp.key)
        f.add_callbacks(self._check_recipient, self._handle_not_found,
                        ebargs=(recp, ), cbargs=(recp, ))
        return f

    @replay.journaled
    def _handle_not_found(self, state, fail, recp):
        fail.trap(NotFoundError)
        return self._forget_recipient(recp)

    @replay.journaled
    def _check_recipient(self, state, desc, recp):
        self.log("Descriptor is still there, waiting patiently for the agent.")

        new_recp = IRecipient(desc)
        if recp != new_recp:
            return self._update_recipient(recp, new_recp)

    ### methods for handling the list of notifications ###

    @replay.journaled
    def notify(self, state, notifications):
        '''
        Call this to schedule sending partner notification.
        '''

        def do_append(desc, notifications):
            for notification in notifications:
                if not isinstance(notification, monitor.PendingNotification):
                    raise ValueError("Expected notify() params to be a list "
                                     "of PendingNotification instance, got %r."
                                     % notification)
                key = str(notification.recipient.key)
                if key not in desc.pending_notifications:
                    desc.pending_notifications[key] = list()
                desc.pending_notifications[key].append(notification)

        return state.agent.update_descriptor(do_append, notifications)

    @replay.immutable
    def _iter_outbox(self, state):
        desc = state.agent.get_descriptor()
        return desc.pending_notifications.iteritems()

    @replay.immutable
    def _get_first_pending(self, state, agent_id):
        desc = state.agent.get_descriptor()
        pending = desc.pending_notifications.get(agent_id, list())
        if pending:
            return pending[0]

    @replay.journaled
    def _remove_notification(self, state, recp, notification):

        def do_remove(desc, recp, notification):
            try:
                desc.pending_notifications[recp.key].remove(notification)
                if not desc.pending_notifications[recp.key]:
                    del(desc.pending_notifications[recp.key])
            except (ValueError, KeyError, ):
                self.warning("Tried to remove notification %r for "
                             "agent_id %r from %r, but not found",
                             notification, recp.key,
                             desc.pending_notifications)

        return state.agent.update_descriptor(do_remove, recp, notification)

    @replay.journaled
    def _forget_recipient(self, state, recp):

        def do_remove(desc, recp):
            res = desc.pending_notifications.pop(str(recp.key))

        return state.agent.update_descriptor(do_remove, recp)

    @replay.journaled
    def _update_recipient(self, state, old, new):
        old = IRecipient(old)
        new = IRecipient(new)
        if old.key != new.key:
            raise AttributeError("Tried to subsituted recipient %r with %r, "
                                 "the key should be the same!" % (old, new))

        def do_update(desc, recp):
            if not desc.pending_notifications.get(recp.key, None):
                return
            for notification in desc.pending_notifications[recp.key]:
                notification.recipient = recp

        return state.agent.update_descriptor(do_update, new)
