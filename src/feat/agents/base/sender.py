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
from feat.agents.base import task, replay, requester

from feat.common import defer, fiber, formatable
from feat.agents.application import feat

from feat.agents.monitor.interface import IClerk, DEFAULT_NOTIFICATION_PERIOD
from feat.agents.monitor.interface import PatientState
from feat.interface.protocols import ProtocolFailed
from feat.interface.recipient import IRecipient
from feat.database.interface import NotFoundError


class AgentMixin(object):

    def initiate(self):
        desc = self.get_descriptor()
        if not hasattr(desc, 'pending_notifications'):
            raise ValueError("Agent using this mixin, should have "
                             "'pending_notification' dictionary field"
                             "in his descriptor")

    @replay.mutable
    def startup(self, state):
        config = state.medium.get_configuration()
        period = config.notification_period
        clerk = getattr(state, 'clerk', None)
        proto = state.medium.initiate_protocol(NotificationSender,
                                               clerk=clerk,
                                               period=period)
        state.notification_sender = proto

    @replay.immutable
    def has_empty_outbox(self, state):
        return state.notification_sender.has_empty_outbox()


@feat.register_restorator
class PendingNotification(formatable.Formatable):

    type_name = 'notification'

    formatable.field('type', None)
    formatable.field('origin', None)
    formatable.field('payload', None)
    formatable.field('recipient', None)


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
            self.debug('Pending notifications keys are: %r',
                       desc.pending_notifications.keys())
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
        if recp != new_recp and new_recp.route is not None:
            return self._update_recipient(recp, new_recp)

    ### methods for handling the list of notifications ###

    @replay.journaled
    def notify(self, state, notifications):
        '''
        Call this to schedule sending partner notification.
        '''

        def do_append(desc, notifications):
            for notification in notifications:
                if not isinstance(notification, PendingNotification):
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
            desc.pending_notifications.pop(str(recp.key))

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
