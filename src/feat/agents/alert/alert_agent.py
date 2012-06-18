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
from zope.interface import implements

from feat.common import formatable, text_helper, fiber
from feat.agents.base import agent, replay, descriptor, collector
from feat.agents.base import dependency, manager, task

from feat.agencies import document, recipient, message
from feat.agents.common import export, monitor, nagios as cnagios, rpc
from feat.agents.alert import nagios, simulation
from feat.agents.application import feat

from feat.interface.protocols import InterestType
from feat.interface.agency import ExecMode
from feat.interface.alert import IAlert
from feat.interface.agent import IAlertAgent
from feat.agents.alert.interface import INagiosSenderLabourFactory


@feat.register_descriptor("alert_agent")
class Descriptor(descriptor.Descriptor):
    pass


header = text_helper.format_block("""
define service{
    name                    passive-service
    use                     generic-service
    check_freshness         1
    passive_checks_enabled  1
    active_checks_enabled   0
    is_volatile             0
    flap_detection_enabled  0
    notification_options    w,u,c,s
    freshness_threshold     57600     ;12hr
}
""")


service_template = text_helper.format_block("""
define service {
    use                    passive-service
    check_command          check_dummy!3!"No Data Received"
    host_name              %(hostname)s
    service_description    %(agent_id)s-%(name)s
    action_url             %(gateway_url)sagents/%(agent_id)s
}
""")


@feat.register_restorator
class AlertAgentConfiguration(document.Document):

    type_name = 'alert_agent_conf'
    document.field('doc_id', u'alert_agent_conf', '_id')
    document.field('enabled', True)
    document.field('monitor', u'')#u'monitor01.bcn.fluendo.net')
    document.field('config_file', u'/etc/nagios/send_nsca.cfg')
    document.field('send_nsca', u'/usr/sbin/send_nsca')
    document.field('config_header', unicode(header))
    document.field('service_template', unicode(service_template))


feat.initial_data(AlertAgentConfiguration)


@feat.register_restorator
class ReceivedAlerts(formatable.Formatable):

    formatable.field('received_count', 0)
    formatable.field('name', None)
    formatable.field('agent_id', None)
    formatable.field('severity', None)
    formatable.field('hostname', None)
    formatable.field('status_info', None)


@feat.register_agent('alert_agent')
class AlertAgent(agent.BaseAgent):

    implements(IAlertAgent)

    restart_strategy = monitor.RestartStrategy.local

    migratability = export.Migratability.locally

    dependency.register(INagiosSenderLabourFactory,
                        nagios.Labour, ExecMode.production)
    dependency.register(INagiosSenderLabourFactory,
                        simulation.NagiosLabour, ExecMode.test)
    dependency.register(INagiosSenderLabourFactory,
                        simulation.NagiosLabour, ExecMode.simulation)

    @replay.mutable
    def initiate(self, state):
        state.medium.register_interest(AlertsCollector)

        config = state.medium.get_configuration()
        state.nagios = self.dependency(INagiosSenderLabourFactory, self,
                                       config)
        # (hostname, agent_id, service_name) -> ReceivedAlerts
        state.alerts = dict()

        state.config_notifier = cnagios.create_poster(self)
        state.medium.initiate_protocol(PushNagiosStatus, 3600) # once an hour

    @replay.journaled
    def on_configuration_change(self, state, config):
        self._notify_change_config(changed=True)

    ### public ###

    @replay.journaled
    def rescan_shard(self, state, force_update_notification=False):
        recp = recipient.Broadcast(AlertsDiscoveryManager.protocol_id,
                                   self.get_shard_id())
        prot = state.medium.initiate_protocol(AlertsDiscoveryManager, recp)
        f = prot.notify_finish()
        f.add_errback(self._expire_handler) # defined in base class
        f.add_callback(self._parse_discovery_response)
        if force_update_notification:
            f.add_callback(fiber.override_result, True)
        f.add_callback(self._notify_change_config)
        return f

    @rpc.publish
    @replay.immutable
    def push_notifications(self, state):
        '''
        Triggered by nagios_agent after he has restarted the nagios in order
        to get the fresh notifications there.
        This method is also run once an hour by recurring task, so that
        nagios wouldnt ever have to run check_dummy check.'''
        self.debug("Pushing all notifications to nagios.")
        f = fiber.wrap_defer(state.nagios.send, state.alerts.values())
        f.add_callback(fiber.override_result, None)
        return f

    ### IAlertAgent (used by model) ###

    @replay.immutable
    def get_alerts(self, state):
        return state.alerts.values()

    @replay.immutable
    def get_raised_alerts(self, state):
        return [x for x in state.alerts.itervalues()
                if x.received_count > 0]

    @replay.immutable
    def generate_nagios_service_cfg(self, state):
        c = state.medium.get_configuration()
        gateway_url = state.medium.get_base_gateway_url()
        res = c.config_header
        for service in state.alerts.itervalues():
            params = dict(hostname=service.hostname,
                          agent_id=service.agent_id,
                          name=service.name,
                          gateway_url=gateway_url)
            res += c.service_template % params
        return res.encode('utf8')

    ### receiving alert notifications ###

    @replay.mutable
    def alert_raised(self, state, alert):
        r = self._find_entry(alert)
        should_notify = (r.received_count == 0 or
                         r.status_info != alert.status_info)
        r.received_count += 1
        r.status_info = alert.status_info
        if should_notify:
            return fiber.wrap_defer(state.nagios.send, [r])

    @replay.mutable
    def alert_resolved(self, state, alert):
        r = self._find_entry(alert)
        should_notify = (r.received_count > 0 or
                         r.status_info != alert.status_info)
        r.received_count = 0
        r.status_info = alert.status_info
        if should_notify:
            return fiber.wrap_defer(state.nagios.send, [r])

    ### private ###

    @replay.immutable
    def _notify_change_config(self, state, changed):
        if changed:
            state.config_notifier.notify(self.generate_nagios_service_cfg())

    @replay.mutable
    def _find_entry(self, state, alert):
        key = (alert.hostname, alert.agent_id, alert.name)
        if key not in state.alerts:
            state.alerts[key] = ReceivedAlerts(
                name=alert.name,
                agent_id=alert.agent_id,
                severity=alert.severity,
                hostname=alert.hostname)
            self.info("Received alert for service we don't know, triggering "
                      "shard rescan in 1 sec. Service: %r", key)
            self.call_later(1, self.rescan_shard,
                            force_update_notification=True)
        return state.alerts[key]

    @replay.mutable
    def _parse_discovery_response(self, state, response):
        changed = False
        old_keys = state.alerts.keys()
        for agent in response:
            for alert in agent.alerts:
                key = (agent.hostname, agent.agent_id, alert.name)
                if key in old_keys:
                    old_keys.remove(key)
                    continue
                changed = True
                state.alerts[key] = ReceivedAlerts(
                    name=alert.name,
                    agent_id=agent.agent_id,
                    severity=alert.severity,
                    hostname=agent.hostname)
        for key in old_keys:
            changed = True
            del(state.alerts[key])
        return changed


class AlertsDiscoveryManager(manager.BaseManager):

    protocol_id = 'discover-alerts'
    announce_timeout = 2

    @replay.journaled
    def initiate(self, state):
        state.providers = list()
        state.medium.announce(message.Announcement())

    @replay.mutable
    def bid(self, state, bid):
        state.providers.append(bid.payload)
        state.medium.reject(bid, message.Rejection())

    @replay.immutable
    def expired(self, state):
        return state.providers


class AlertsCollector(collector.BaseCollector):

    protocol_id = 'alert'
    interest_type = InterestType.public

    @replay.immutable
    def notified(self, state, msg):
        action, alert = msg.payload
        handler = getattr(state.agent, "alert_" + action, None)
        if not handler:
            raise ValueError("Received malformed alert notifications. Action "
                             "is: %s." % (action, ))
        if not IAlert.providedBy(alert):
            raise TypeError("Received malformed alert notifications. "
                            "%r didn't provide IAlert" % (alert, ))
        return handler(alert)


class PushNagiosStatus(task.StealthPeriodicTask):

    @replay.immutable
    def run(self, state):
        state.agent.push_notifications()
