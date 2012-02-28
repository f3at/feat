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
from feat.common import enum
from feat.agents.base import replay, poster
from feat.agencies import message, recipient
from feat.interface.protocols import *


class Severity(enum.Enum):

    low, medium, high, recover = range(4)


class AgentMixin(object):

    @replay.mutable
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
