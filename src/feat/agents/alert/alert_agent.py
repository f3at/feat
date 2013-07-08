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

from feat.common import text_helper, fiber
from feat.agents.base import agent, replay, descriptor, collector
from feat.agents.base import dependency, manager, task

from feat.agencies import recipient, message
from feat.database import document, view
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
    service_description    %(description)s
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
class AlertService(document.Document):

    type_name = 'alert_service'

    document.field('name', None)
    document.field('severity', None)
    document.field('hostname', None)
    document.field('status_info', None)
    document.field('description', None)
    document.field('persistent', False)

    def __init__(self, received_count=0, agent_id=None, **kwargs):
        super(AlertService, self).__init__(**kwargs)
        # fields defined below are instance variable not document fields,
        # they would not get saved to the database
        self.received_count = received_count
        self.agent_id = agent_id

    def restored(self):
        super(AlertService, self).restored()
        self.received_count = 0
        self.agent_id = None

    @classmethod
    def from_alert(cls, alert, agent):
        descr = (alert.description or
                 "%s-%s" % (agent.agent_id, alert.name))
        return cls(name=alert.name,
                   agent_id=agent.agent_id,
                   severity=alert.severity,
                   description=descr,
                   persistent=alert.persistent,
                   hostname=agent.hostname)


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
        # (hostname, description) -> AlertService
        state.alerts = dict()

        state.config_notifier = cnagios.create_poster(self)
        f = self.query_view(view.DocumentByType, key=AlertService.type_name,
                            include_docs=True)
        f.add_callback(self._load_persistent_services)
        return f

    @replay.journaled
    def startup(self, state):
        state.medium.initiate_protocol(PushNagiosStatus, 3600) # once an hour

    @replay.mutable
    def _load_persistent_services(self, state, view_result):
        self.info("Loading info about persistent services. %d entries found",
                  len(view_result))
        for doc in view_result:
            key = self._alert_key(doc)
            if key not in state.alerts:
                state.alerts[key] = doc
            else:
                # Because of concurency in receiving alerts and scaning shards
                # we might have duplicates in documents describing persitent
                # alert. Here they are removed
                self.call_next(state.medium.delete_document, doc)

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
    @replay.journaled
    def push_notifications(self, state):
        '''
        Triggered by nagios_agent after he has restarted the nagios in order
        to get the fresh notifications there.
        This method is also run once an hour by recurring task, so that
        nagios wouldnt ever have to run check_dummy check.'''
        self.debug("Pushing all notifications to nagios.")

        # We are pushing only the alerts which has the agent responsible for
        # them. As long as noone claims responsiblity the state should not
        # change.
        to_send = [x for x in state.alerts.itervalues() if x.agent_id]
        f = fiber.wrap_defer(state.nagios.send, to_send)
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
                          description=service.description,
                          gateway_url=gateway_url)
            res += c.service_template % params
        return res.encode('utf8')

    @replay.mutable
    def delete_alert(self, state, alert):
        key = self._alert_key(alert)
        if key in state.alerts:
            self.info('Removing alert from agent state.')
            del state.alerts[key]
        if alert.persistent:
            self.info("Removing alert definition from database. Doc id: %s",
                      alert.doc_id)
            f = self.delete_document(alert)
            f.add_callback(fiber.override_result, None)
            return f

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

    def _alert_key(self, alert):
        return (alert.hostname, alert.description or
                "-".join([alert.agent_id, alert.name]))

    @replay.mutable
    def _find_entry(self, state, alert):
        key = self._alert_key(alert)
        if key not in state.alerts:
            state.alerts[key] = new = AlertService.from_alert(alert, alert)
            self.info("Received alert for service we don't know, triggering "
                      "shard rescan in 1 sec. Service: %r", key)
            self.call_later(1, self.rescan_shard,
                            force_update_notification=True)
            if new.persistent:
                self.info("Persisting the service definition in couchdb")
                self.call_next(state.medium.save_document, new)
        elif state.alerts[key].agent_id is None:
            # the alert was loaded from the database, there is a new agent
            # responsible for it, we should save its ID after the restart
            state.alerts[key].agent_id = alert.agent_id
        return state.alerts[key]

    @replay.mutable
    def _parse_discovery_response(self, state, response):
        changed = False
        old_keys = state.alerts.keys()
        for agent in response:
            for alert in agent.alerts:
                key = (agent.hostname, alert.description
                       or "-".join([agent.agent_id, alert.name]))
                if key in old_keys:
                    old_keys.remove(key)
                    continue
                changed = True
                state.alerts[key] = new = AlertService.from_alert(alert, agent)
                if new.persistent:
                    self.info("Persisting the service definition in couchdb. "
                              "%r", new)
                    self.call_next(state.medium.save_document, new)
                status = agent.statuses.get(alert.name)
                if status:
                    state.alerts[key].received_count = status[0]
                    state.alerts[key].status_info = status[1]
        for key in old_keys:
            if not state.alerts[key].persistent:
                # don't remove persistent services, even if there is no agent
                # responsible for them at the moment
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
