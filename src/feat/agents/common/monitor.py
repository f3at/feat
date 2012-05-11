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
from twisted.python import failure

from feat.agencies import retrying
from feat.agents.base import replay, task, partners, descriptor, dependency
from feat.agents.base import alert
from feat.agents.common import rpc
from feat.common import fiber, formatable
from feat.agents.application import feat

# To access from this module
from feat.agents.monitor.interface import RestartStrategy
from feat.agents.monitor.interface import RestartFailed, MonitoringFailed
from feat.agents.monitor.interface import IPacemakerFactory, IPacemaker
from feat.agents.monitor.pacemaker import Pacemaker, FakePacemaker

from feat.interface.agency import ExecMode


__all__ = ['notify_restart_complete',
           'Descriptor', 'RestartFailed', 'RestartStrategy',
           'PartnerMixin', 'AgentMixin',
           'IPacemakerFactory', 'IPacemaker',
           'Pacemaker', 'FakePacemaker']


def notify_restart_complete(agent, monitor, recp):
    '''
    Use this for finalizing custom restart procedure of some agent. If
    his partner accepted responsibility in on_died() callback, he needs
    to notify the monitor agent the the restart procedure is complete.
    @param agent: Agent performing the restart
    @param monitor: IRecipient of the monitor agent who sent us the
                    on_died() notification
    @param recp: IRecipient of the agent who died and got restarted.
    '''
    return agent.call_remote(monitor, 'restart_complete', recp)


def discover(agent, shard=None):
    shard = shard or agent.get_shard_id()
    return agent.discover_service("monitoring", timeout=1, shard=shard)


@feat.register_restorator
class MonitoringInfo(formatable.Formatable):

    type_name = "monitoring-info"

    formatable.field("instance_id", None)
    formatable.field("agent_type", None)
    formatable.field("location", None)


class PartnerMixin(object):
    '''When used as a base class for a partner that do not redefine
    on_goodbye(), this class should be appear before any BasePartner subclass
    in the list of super classes. If not, the BasePartner on_goodbye() will
    be called and nothing will happen.
    See feat.agents.base.agent.BasePartner.'''

    def initiate(self, agent):
        f = agent.get_document("monitor_agent_conf")
        f.add_callback(self._start_heartbeat, agent)
        return f

    def on_goodbye(self, agent):
        agent.stop_heartbeat(self.recipient)
        agent.lookup_monitor()

    def on_buried(self, agent):
        agent.stop_heartbeat(self.recipient)
        agent.lookup_monitor()

    def _start_heartbeat(self, doc, agent):
        return agent.start_heartbeat(self.recipient, doc.heartbeat_period)


@feat.register_restorator
class MonitorMissing(alert.BaseAlert):
    name = 'monitoring'
    severity = alert.Severity.warn


class AgentMixin(object):

    restart_strategy = RestartStrategy.buryme

    dependency.register(IPacemakerFactory, Pacemaker, ExecMode.production)
    dependency.register(IPacemakerFactory, FakePacemaker, ExecMode.test)
    dependency.register(IPacemakerFactory, FakePacemaker, ExecMode.simulation)

    need_local_monitoring = True

    alert.may_raise(MonitorMissing)

    @replay.immutable
    def startup(self, state):
        if not state.partners.monitors:
            self.lookup_monitor()

    @replay.mutable
    def cleanup_monitoring(self, state):
        self._lazy_mixin_init()
        for pacemaker in state.pacemakers.values():
            pacemaker.cleanup()
        state.pacemakers.clear()

    @replay.mutable
    def start_heartbeat(self, state, monitor, period):
        self._lazy_mixin_init()
        pacemaker = self.dependency(IPacemakerFactory, self, monitor, period)
        pacemaker.startup()
        state.pacemakers[monitor.key] = pacemaker

    @replay.mutable
    def stop_heartbeat(self, state, monitor):
        self._lazy_mixin_init()
        if monitor.key in state.pacemakers:
            del state.pacemakers[monitor.key]

    @replay.immutable
    def lookup_monitor(self, state):
        if self.need_local_monitoring:
            Factory = retrying.RetryingProtocolFactory
            factory = Factory(SetupMonitoringTask, max_delay=60, busy=False,
                              alert_after=5, alert_service='monitoring')
            self.initiate_protocol(factory)

    def query_monitoring_info(self, recipient):
        return self.call_remote_ex(recipient,
                                   "get_monitoring_info", timeout=2)

    @rpc.publish
    @replay.immutable
    def get_monitoring_info(self, state):
        desc = state.medium.get_descriptor()
        return MonitoringInfo(instance_id=desc.instance_id,
                              agent_type=self.descriptor_type,
                              location=state.medium.get_hostname())

    ### Private Methods ###

    @replay.mutable
    def _lazy_mixin_init(self, state):
        if not hasattr(state, "pacemakers"):
            state.pacemakers = {} # {AGENT_ID: IPacemaker}


class SetupMonitoringTask(task.BaseTask):

    busy = False
    protocol_id = "setup-monitoring"

    def __init__(self, *args, **kwargs):
        task.BaseTask.__init__(self, *args, **kwargs)

    @replay.entry_point
    def initiate(self, state, shard=None):
        self.debug("Looking up a monitor for %s %s",
                   state.agent.descriptor_type, state.agent.get_full_id())
        f = fiber.Fiber(state.medium.get_canceller())
        f.add_callback(discover, shard)
        f.add_callback(self._start_monitoring)

        resolve_status = ("%s is partnered with the MA" %
                          (state.agent.descriptor_type, ))
        f.add_callback(fiber.drop_param,
                       state.agent.resolve_alert, 'monitoring',
                       resolve_status)
        return f.succeed(state.agent)

    @replay.journaled
    def _start_monitoring(self, state, monitors):
        if not monitors:
            ex = MonitoringFailed("No monitor agent found in shard for %s %s"
                                  % (state.agent.descriptor_type,
                                     state.agent.get_full_id()))
            return fiber.fail(ex)

        monitor = monitors[0]
        self.info("Monitor found for %s %s: %s", state.agent.descriptor_type,
                  state.agent.get_full_id(), monitor.key)
        f = state.agent.establish_partnership(monitor)
        f.add_errback(failure.Failure.trap, partners.DoublePartnership)
        return f


@feat.register_descriptor("monitor_agent")
class Descriptor(descriptor.Descriptor):

    # agent_id -> [PendingNotification]
    formatable.field('pending_notifications', dict())
