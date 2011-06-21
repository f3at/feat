# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from feat.common import manhole, text_helper, serialization, formatable
from feat.agents.base import (agent, replay, descriptor, alert, collector,
                              document, dbtools, dependency, )
from feat.interface.protocols import *
from feat.interface.agency import *

from feat.agents.alert import production, simulation
from feat.agents.alert.interface import *


@descriptor.register("alert_agent")
class Descriptor(descriptor.Descriptor):
    pass


@serialization.register
class AlertMailConfiguration(formatable.Formatable):

    formatable.field('fromaddr', 'feat.alert.agent@gmail.com')
    formatable.field('toaddrs', 'feat.alert.agent@gmail.com')
    formatable.field('username', 'feat.alert.agent@gmail.com')
    formatable.field('password', 'flUm0tI0n')
    formatable.field('SMTP', 'smtp.gmail.com:587')


@document.register
class AlertAgentConfiguration(document.Document):

    document_type = 'alert_agent_conf'
    document.field('doc_id', u'alert_agent_conf', '_id')
    document.field('mail_config', AlertMailConfiguration())

dbtools.initial_data(AlertAgentConfiguration)


@agent.register('alert_agent')
class AlertAgent(agent.BaseAgent, alert.AgentMixin):

    dependency.register(IEmailSenderLabourFactory,
                        production.Labour, ExecMode.production)
    dependency.register(IEmailSenderLabourFactory,
                        simulation.Labour, ExecMode.test)
    dependency.register(IEmailSenderLabourFactory,
                        simulation.Labour, ExecMode.simulation)

    @replay.mutable
    def initiate(self, state):
        interest = state.medium.register_interest(AlertsCollector)
        interest.bind_to_lobby()
        state.labour = self.dependency(IEmailSenderLabourFactory, self)
        state.alerts = dict()

    @replay.immutable
    def startup(self, state):
        state.labour.startup()

    @replay.mutable
    def append_alert(self, state, alert_msg, severity):
        alert = state.alerts.get(alert_msg, None)
        if alert is None:
            self.log("Received unknown alert: %s" % alert_msg)
            state.alerts[alert_msg] = severity
            state.labour.send(state.medium.get_configuration().mail_config,
                              alert_msg + ". Severity " + severity.name)
        else:
            self.log("Received known alert: %s" % alert_msg)
            if severity > alert:
                state.alerts[alert_msg] = severity
                state.labour.send(state.medium.get_configuration().mail_config,
                        alert_msg + ". Increased severity to " + severity.name)

    @manhole.expose()
    @replay.mutable
    def remove_alert(self, state, alert_msg, severity):
        state.alerts.pop(alert_msg, None)

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
