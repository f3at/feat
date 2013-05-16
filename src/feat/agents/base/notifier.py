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
import uuid

from feat.common import serialization, fiber, defer
from feat.agents.base import replay
from feat.agents.application import feat


class TimeoutError(Exception):
    pass


class Notification(object):
    """I'm an internal object to store data inside the AgentNotifier."""

    def __init__(self):
        self.id = str(uuid.uuid1())
        self.deferred = defer.Deferred()
        self.cancellation_id = None


@feat.register_restorator
class AgentNotifier(serialization.Serializable):

    def __init__(self, agent):
        # notification_name -> { notification.id -> Notification }
        self._notifications = dict()
        self.agent = agent

    def wait(self, notification, timeout=None):
        return fiber.wrap_defer(self._wait, notification, timeout)

    def callback(self, notification, result):
        self.agent.call_next(self._callback, notification, result)

    def errback(self, notification, failure):
        self.agent.call_next(self._errback, notification, failure)

    ### Private methods ###

    def _store(self, notification_name, notification):
        if notification_name not in self._notifications:
            self._notifications[notification_name] = dict()
        self._notifications[notification_name][notification.id] = notification

    def _pop(self, notification_name):
        if notification_name in self._notifications:
            notifications = self._notifications.pop(notification_name)
            for notification in notifications.values():
                c_id = notification.cancellation_id
                if c_id:
                    self.agent.cancel_delayed_call(c_id)
            return notifications.values()

    def _expire(self, notification_name, n_id):
        try:
            notification = self._notifications[notification_name].pop(n_id)
        except KeyError:
            self.agent.warning('Tried to expire nonexisting notification. '
                               'Name: %r, Id: %r.', notification_name, n_id)
            return
        msg = 'Timeout expired waiting for the event %r' % notification_name
        notification.deferred.errback(TimeoutError(msg))

    def _wait(self, notification_name, timeout):
        # Creation of Deferred needs to be outside the ball.
        # This method should be only run from the fiber
        notification = Notification()
        if timeout:
            notification.cancellation_id = self.agent.call_later(
                timeout, self._expire, notification_name, notification.id)

        self._store(notification_name, notification)
        return notification.deferred

    def _callback(self, notification_name, result):
        notifications = self._pop(notification_name)
        if notifications:
            for notification in notifications:
                notification.deferred.callback(result)

    def _errback(self, notification_name, failure):
        notifications = self._pop(notification_name)
        if notifications:
            for notification in notifications:
                notification.deferred.errback(failure)

    def __eq__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return True

    def __ne__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return False


class AgentMixin(object):

    @replay.mutable
    def initiate(self, state):
        state.notifier = AgentNotifier(self)

    @replay.journaled
    def wait_for_event(self, state, name, timeout=None):
        return state.notifier.wait(name, timeout)

    @replay.immutable
    def callback_event(self, state, name, value):
        state.notifier.callback(name, value)

    @replay.immutable
    def errback_event(self, state, name, failure):
        state.notifier.errback(name, failure)
