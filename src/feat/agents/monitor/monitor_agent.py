# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from zope.interface import implements, classProvides

import operator
import copy

from feat.agents.base import (agent, contractor, partners, task, problem,
                              requester, message, replay, recipient, )
from feat.agents.common import raage, host, rpc, shard
from feat.common import fiber, serialization, defer, time

from feat.agents.common.monitor import *
from feat.interface.protocols import *


@serialization.register
class MonitoredPartner(partners.BasePartner):

    type_name = 'monitor->agent'

    def __init__(self, *args, **kwargs):
        partners.BasePartner.__init__(self, *args, **kwargs)
        self.instance_id = None

    def initiate(self, agent):
        return self._update_instance_id(agent)

    def on_restarted(self, agent, moved):
        return self._update_instance_id(agent)

    @fiber.woven
    def _update_instance_id(self, agent):
        f = agent.get_document(self.recipient.key)
        f.add_callback(
            lambda doc: setattr(self, 'instance_id', doc.instance_id))
        return f


@serialization.register
class MonitorPartner(MonitoredPartner):
    type_name = 'monitor->monitor'


@serialization.register
class ShardPartner(MonitoredPartner):

    type_name = 'monitor->shard'

    def initiate(self, agent):
        f = MonitoredPartner.initiate(self, agent)
        f.add_callback(fiber.drop_result, agent.call_next,
                       agent.update_neighbour_monitors)
        return f


class Partners(partners.Partners):

    # makes all our partners include role=u'monitor'
    # in the object representing us
    default_role = u'monitor'

    default_handler = MonitoredPartner

    partners.has_one('shard', 'shard_agent', ShardPartner)
    partners.has_many('monitors', 'monitor_agent', MonitorPartner)


@agent.register('monitor_agent')
class MonitorAgent(agent.BaseAgent, rpc.AgentMixin):

    implements(shard.IShardNotificationHandler)

    partners_class = Partners

    restart_strategy = RestartStrategy.monitor

    @replay.entry_point
    def initiate(self, state):
        agent.BaseAgent.initiate(self)
        rpc.AgentMixin.initiate(self)

        shard.register_for_notifications(self)

        state.medium.register_interest(
            contractor.Service(MonitorContractor))
        state.medium.register_interest(MonitorContractor)
        state.medium.register_interest(
            problem.SolveProblemInterest(DeadAgent()))

        # agent_id -> HandleDeath instance
        state.handler_tasks = dict()

    @replay.mutable
    def handle_agent_death(self, state, recp):
        recp = recipient.IRecipient(recp)
        task = state.handler_tasks.get(recp.key, None)
        if task:
            return task.notify_finish()
        else:
            task = self.initiate_task(HandleDeath, recp)
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
        recp = recipient.IRecipient(recp)
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
                task = self.initiate_task(HandleDeath, partner.recipient)
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
        recipients = set([p.recipient for p in monitors])
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
        #FIXME: Shouldn't we have something like partners.unlink that do this ?
        partner = self.find_partner(recipient)
        if partner:
            f = requester.say_goodbye(self, recipient, None)
            f.add_callback(fiber.drop_result, self.remove_partner, partner)
            return f


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

    protocol_id = 'handle-death'

    # timeout for this task is dynamic
    timeout = None

    @replay.entry_point
    def initiate(self, state, recp):
        state.recp = recp
        state.descriptor = None
        state.factory = None
        state.attempt = 0
        state.timeout_call_id = None
        state.monitors = None

        state.agent.call_next(self._bind_unregistering_self)

        f = state.agent.get_document(state.recp.key)
        f.add_callback(self._store_descriptor)
        f.add_callback(fiber.drop_result, self._determine_factory)
        f.add_callback(fiber.drop_result, self._start_collective_solver)
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
        state.medium.finish(None)

    @replay.mutable
    def _start_collective_solver(self, state):
        '''
        Determines who from all the monitors monitoring this agent should
        resolve the issue.
        '''
        own_address = state.agent.get_own_address()
        monitors = [recipient.IRecipient(x) for x in state.descriptor.partners
                    if x.role == u'monitor']
        im_included = any([x == own_address for x in monitors])
        if not im_included:
            monitors.append(own_address)
        # this object is going to be stored in the state of CollectiveSolver,
        # we need to deepcopy it not to share a refrence
        state.monitors = copy.deepcopy(monitors)
        state.agent.initiate_task(problem.CollectiveSolver,
                                  self, monitors)
        return task.NOT_DONE_YET

    ### IProblem ###

    @replay.immutable
    def get_keywords(self, state):
        res = {'instance_id': state.descriptor.instance_id,
               'agent_id': state.descriptor.doc_id}
        return res

    def wait_for_solution(self):
        return self.notify_finish()

    @replay.immutable
    def solve_for(self, state, solution, recp):
        return state.agent.call_remote(recp, 'restart_handeled',
                                       state.descriptor.doc_id)

    @replay.journaled
    def solve_localy(self, state):
        f = self._retry()
        f.add_callback(fiber.drop_result, self.notify_finish)
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
            self.debug('Agent %r is going to by burried according to his '
                       'last will.', state.factory.descriptor_type)
            f = self._send_burried_notifications()
            f.add_callback(fiber.override_result, self)
            return f
        else:
            f = self._send_died_notifications()
            f.add_both(self._ensure_someone_took_responsability)
            return f

    @replay.mutable
    def _send_died_notifications(self, state):
        self.log("Sending 'died' notifications to the partners, which are: %r",
                 state.descriptor.partners)
        fibers = list()
        for partner, brothers in self._iter_categorized_partners():
            fibers.append(requester.notify_died(
                state.agent, partner, state.recp, brothers))
        f = fiber.FiberList(fibers, consumeErrors=True)
        f.succeed()
        return f

    @replay.mutable
    def _send_burried_notifications(self, state):
        self.log("Sending 'burried' notifications to the partners, "
                 "which are: %r", state.descriptor.partners)
        fibers = list()
        for partner, brothers in self._iter_categorized_partners():
            fibers.append(requester.notify_burried(
                state.agent, partner, state.recp, brothers))
        f = fiber.FiberList(fibers, consumeErrors=True)
        f.succeed()
        return f

    @replay.mutable
    def _send_restarted_notifications(self, state, new_address):
        self.log("Sending 'restarted' notifications to the partners, "
                 "which are: %r", state.descriptor.partners)
        fibers = list()
        for partner in state.descriptor.partners:
            f = requester.notify_restarted(
                state.agent, partner, state.recp, new_address)
            fibers.append(f)
        f = fiber.FiberList(fibers, consumeErrors=True)
        f.succeed()
        f.add_callback(fiber.drop_result, state.medium.finish, new_address)
        return f

    @replay.mutable
    def _ensure_someone_took_responsability(self, state, responses):
        '''
        Called as a callback for sending *died* notifications to all the
        partners.
        Check if someone has offered to restart the agent.
        If yes, setup expiration call and wait for report.
        If no, initiate doing it on our own.
        '''
        accepted = [response for _, response in responses
                    if isinstance(response, partners.ResponsabilityAccepted)]
        if len(accepted) == 0:
            self.debug('Noone took responsability, I will try to restart '
                       '%r agent myself', state.factory.descriptor_type)

            return self._restart_yourself()
        else:
            expiration_time = max(map(operator.attrgetter('expiration_time'),
                                      accepted))
            time_left = time.left(expiration_time)
            state.timeout_call_id = state.agent.call_later(
                time_left, self._timeout_waiting_for_restart)
            return task.NOT_DONE_YET

    def _timeout_waiting_for_restart(self):
        self.error("Timeout waiting for the responsable agent to send the "
                   "notification. I will retry the whole procedure.")
        return self._retry()

    @replay.mutable
    def _restart_yourself(self, state):
        f = self._clear_host_partner()
        f.add_callback(fiber.drop_result,
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
            self.info('Giving up, just sending burried notifications.')
            f = self._send_burried_notifications()
            f.add_callback(fiber.drop_result, state.medium.finish, None)
            return f
        elif self._cmp_strategy(RestartStrategy.whereever):
            self.info('Trying to find an allocation anywhere in the cluster.')
            f = raage.retrying_allocate_resource(
                state.agent, resources=state.factory.resources,
                categories=state.factory.categories, max_retries=3)
            f.add_callback(self._request_starting_agent)
            f.add_callbacks(state.medium.finish,
                            self._finding_allocation_failed)
            return f
        elif self._cmp_strategy(RestartStrategy.monitor):
            self.info('Taking over the role of the died monitor.')
            f = self._checkup_partners()
            f.add_callback(fiber.drop_result,
                           self._send_burried_notifications)
            f.add_callback(fiber.drop_result, state.medium.finish, None)
            return f
        else:
            state.medium.fail(RestartFailed('Unknown restart strategy: %r' %
                                            (self.factory.restart_strategy, )))

    @replay.immutable
    def _finding_allocation_failed(self, state, fail):
        fail.trap(InitiatorFailed)
        msg = ("Chaos monkey won this time! Despite 3 times trying we "
               "failed to find the allocation for the the %r. "
               "Just sending burried notifications." %
               state.descriptor.document_type)
        exp = RestartFailed(msg)
        f = self._send_burried_notifications()
        f.add_callback(fiber.drop_result, state.medium.fail, exp)
        return f

    @replay.mutable
    def _request_starting_agent(self, state, (allocation_id, recp)):
        # we are setting shard=None here first, because of the logic in
        # Host Agent which prevents it from changing the shard field if it
        # has been set to sth meaningfull (not in [None, 'lobby'])
        f = state.descriptor.set_shard(state.agent, None)
        f.add_callback(self._store_descriptor)
        f.add_callback(fiber.drop_result, host.start_agent,
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

    @replay.immutable
    def _ping_failed(self, state, fail, partner):
        self.debug('Sending ping to the partner %r failed with %r. '
                   'Initializing death handling task.', partner, fail)
        return state.agent.handle_agent_death(partner)

    @replay.immutable
    def _ping_success(self, state, _, partner):
        self.debug('Sending ping to the partner %r was successful. '
                   'Taking over the role of the monitor.', partner)
        return state.agent.establish_partnership(partner)

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
        d.addCallback(defer.drop_result,
                      state.agent._unregister_task,
                      state.recp.key)
        return d


class MonitorContractor(contractor.NestingContractor):

    protocol_id = 'request-monitor'
    interest_type = InterestType.private

    announce_timeout = 10

    @replay.entry_point
    def announced(self, state, announcement):
        msg = message.Bid()
        state.medium.bid(msg)

    @replay.entry_point
    def granted(self, state, grant):
        f = fiber.Fiber()
        f.add_callback(fiber.drop_result, self._create_partner,
                      grant)
        f.add_callbacks(self._finalize, self._granted_failed)
        return f.succeed()

    @replay.mutable
    def _create_partner(self, state, grant):
        f = fiber.Fiber()
        f.add_callback(state.agent.establish_partnership)
        return f.succeed(grant.reply_to)

    @replay.immutable
    def _granted_failed(self, state, failure):
        state.medium._error_handler(failure)
        msg = message.Cancellation(reason=str(failure.value))
        state.medium.defect(msg)

    @replay.immutable
    def _finalize(self, state, _):
        report = message.FinalReport()
        state.medium.finalize(report)
