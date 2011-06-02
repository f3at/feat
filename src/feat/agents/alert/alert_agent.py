# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from feat.common import manhole, text_helper, serialization, formatable
from feat.agents.base import (agent, replay, descriptor, alert, collector,
                              document, dbtools, dependency, )
from feat.interface.protocols import *
from feat.interface.agency import *

from feat.agents.alert import mail, nagios, simulation
from feat.agents.alert.interface import *


@descriptor.register("alert_agent")
class Descriptor(descriptor.Descriptor):
    pass


@serialization.register
class AlertSenderConfiguration(formatable.Formatable):

    formatable.field('enabled', True)


@serialization.register
class AlertMailConfiguration(AlertSenderConfiguration):

    formatable.field('fromaddr', u'feat.alert.agent@gmail.com')
    formatable.field('toaddrs', u'feat.alert.agent@gmail.com')
    formatable.field('username', u'feat.alert.agent@gmail.com')
    formatable.field('password', u'flUm0tI0n')
    formatable.field('SMTP', u'smtp.gmail.com:587')


@serialization.register
class AlertNagiosConfiguration(AlertSenderConfiguration):

    formatable.field('monitor', u'monitor01.bcn.fluendo.net')
    formatable.field('config_file', u'/etc/nagios/send_nsca.cfg')
    formatable.field('send_nsca', u'/usr/sbin/send_nsca')
    formatable.field('svc_descr', u'FLTSERVICE')
    formatable.field('host', u'flt1.livetranscoding.net')


@document.register
class AlertAgentConfiguration(document.Document):

    document_type = 'alert_agent_conf'
    document.field('doc_id', u'alert_agent_conf', '_id')
    document.field('mail_config', AlertMailConfiguration())
    document.field('nagios_config', AlertNagiosConfiguration())

dbtools.initial_data(AlertAgentConfiguration)


@agent.register('alert_agent')
class AlertAgent(agent.BaseAgent, alert.AgentMixin):

    dependency.register(IEmailSenderLabourFactory,
                        mail.Labour, ExecMode.production)
    dependency.register(IEmailSenderLabourFactory,
                        simulation.MailLabour, ExecMode.test)
    dependency.register(IEmailSenderLabourFactory,
                        simulation.MailLabour, ExecMode.simulation)

    dependency.register(INagiosSenderLabourFactory,
                        nagios.Labour, ExecMode.production)
    dependency.register(INagiosSenderLabourFactory,
                        simulation.NagiosLabour, ExecMode.test)
    dependency.register(INagiosSenderLabourFactory,
                        simulation.NagiosLabour, ExecMode.simulation)

    @replay.mutable
    def initiate(self, state):
        interest = state.medium.register_interest(AlertsCollector)
        interest.bind_to_lobby()
        state.notifiers = []
        config = state.medium.get_configuration()
        if config.mail_config.enabled:
            labour = self.dependency(IEmailSenderLabourFactory, self)
            state.notifiers.append(labour)
        if config.nagios_config.enabled:
            labour = self.dependency(INagiosSenderLabourFactory, self)
            state.notifiers.append(labour)
        state.alerts = dict()

    @replay.immutable
    def startup(self, state):
        for labour in state.notifiers:
            labour.startup()

    @replay.mutable
    def append_alert(self, state, alert_msg, severity):
        self.log("Received Alert: %s" % alert_msg)
        alert = state.alerts.get(alert_msg, None)
        if alert and severity == alert:
            self.log('Alert (%s) already sent, discarting it', alert_msg)
            return
        elif alert and severity == alert:
            self.log('Increased alert severity to %s', severity.name)
        state.alerts[alert_msg] = severity
        self.notify_alert(alert_msg, severity)

    @manhole.expose()
    @replay.mutable
    def remove_alert(self, state, alert_msg, severity):
        ralert = state.alerts.pop(alert_msg, None)
        if ralert:
            self.notify_alert(alert_msg, alert.Severity.recover)

    @replay.immutable
    def notify_alert(self, state, alert_msg, severity):
        for labour in state.notifiers:
            labour.send(state.medium.get_configuration(),
                        alert_msg, severity)

    @replay.immutable
    def get_alerts(self, state):
        return state.alerts

    @replay.immutable
    def get_alert(self, state, alert_id):
        return state.alerts.get(alert_id)

    @manhole.expose()
    @replay.immutable
    def list_alerts(self, state):
        t = text_helper.Table(fields=("Severity", "Alert", ),
                lengths=(10, 70 ))

        return t.render((state.alerts[alert].name, alert, )\
                        for alert in state.alerts)


class AlertsCollector(collector.BaseCollector):

    protocol_id = 'alert'
    interest_type = InterestType.public

    def notified(self, msg):
        action, args = msg.payload
        handler = getattr(self, "action_" + action, None)
        if not handler:
            self.warning("Unknown action: %s", action)
            return
        return handler(*args)

    @replay.immutable
    def action_add_alert(self, state, alert_msg, severity):
        state.agent.append_alert(alert_msg, severity)

    @replay.immutable
    def action_resolve_alert(self, state, alert_msg, severity):
        state.agent.remove_alert(alert_msg, severity)
