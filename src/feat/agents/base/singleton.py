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
from feat.agents.base import replay
from feat.common import formatable, fiber, error

from feat.agents.application import feat


@feat.register_restorator
class TaskObserver(formatable.Formatable):

    formatable.field('observer', None)
    formatable.field('retriggered', False)
    formatable.field('protocol_id', None)


class AgentMixin(object):
    '''
    Singleton tasks are tasks which should have only one instance of them
    running at the time. If the task is started while the other instance is
    running it will wait until the existing one finishes, and than run again.
    '''

    @replay.mutable
    def initiate(self, state):
        # protocol_id -> TaskObserver
        state.singleton_tasks = dict()

    @replay.mutable
    def singleton_task(self, state, factory, *args, **kwargs):
        if factory.protocol_id is None:
            # paranoic check just in case
            raise error.FeatError(
                'singleton_task() called for factory %r, which has '
                'protocol_id=None' % (factory, ))
        obs = state.singleton_tasks.get(factory.protocol_id, None)
        if not obs:
            obs = TaskObserver(protocol_id=factory.protocol_id)
            state.singleton_tasks[factory.protocol_id] = obs
        if obs.observer and obs.observer.active():
            if not obs.retriggered:
                obs.retriggered = True
                self.call_next(self._retrigger_task, factory, *args, **kwargs)
        else:
            task = self.initiate_protocol(factory, *args, **kwargs)
            obs.observer = state.medium.observe(task.notify_finish)
            obs.retriggered = False

    @replay.journaled
    def _retrigger_task(self, state, factory, *args, **kwargs):
        obs = state.singleton_tasks[factory.protocol_id]
        f = obs.observer.notify_finish()
        f.add_both(fiber.drop_param, self.singleton_task, factory,
                   *args, **kwargs)
        return f
