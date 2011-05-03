# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import uuid

from feat.common import defer, enum
from feat.agents.base import replay, poster, message, recipient, collector
from feat.interface.protocols import *


class Severity(enum.Enum):

    low, medium, high = range(3)


class AgentMixin(object):

    # FIXME this should be marked as @replay.mutable after we get rid of
    # bug in annotations/recorded calls

    def initiate(self, state):
        state.alerter = self._new_alert(self)

    def _new_alert(self, agent):
        recp = recipient.Broadcast(AlertPoster.protocol_id, 'lobby')
        return agent.initiate_protocol(AlertPoster, recp)

    @replay.mutable
    def raise_alert(self, state, alert_msg, severity):
        state.alerter.post_alert(alert_msg, severity)

    @replay.mutable
    def resolve_alert(self, state, alert_msg, severity):
        state.alerter.post_resolve_alert(alert_msg, severity)


class AlertPoster(poster.BasePoster):

    protocol_id = 'alert'

    @replay.side_effect
    def post_alert(self, alert_msg, severity):
        self.notify("add_alert", alert_msg, severity)

    @replay.side_effect
    def post_resolve_alert(self, alert_msg, severity):
        self.notify("resolve_alert", alert_msg, severity)

    def notify(self, *args, **kwargs):
        self._build_alert(self._pack_payload(*args, **kwargs))

    ### Private methods ###

    def _pack_payload(self, action, alert_msg, severity):
        return action, (alert_msg, severity)

    @replay.immutable
    def _build_alert(self, state, payload):
        msg = message.Notification()
        msg.payload = payload
        return state.medium.post(msg)
