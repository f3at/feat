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
from zope.interface import implements

from feat.agents.base import protocols, replay
from feat.common import reflect, defer, error
from feat.agents.application import feat

from feat.interface.task import ITaskFactory, IAgentTask, NOT_DONE_YET


class Meta(type(replay.Replayable)):

    implements(ITaskFactory)

    def __init__(cls, name, bases, dct):
        cls.type_name = reflect.canonical_name(cls)
        cls.application.register_restorator(cls)
        super(Meta, cls).__init__(name, bases, dct)


class BaseTask(protocols.BaseInitiator):
    """
    I am a base class for managers of tasks
    """

    __metaclass__ = Meta
    application = feat

    implements(IAgentTask)

    protocol_type = "Task"
    protocol_id = None
    busy = True # Busy tasks will not be idle

    timeout = 10

    @replay.immutable
    def cancel(self, state):
        state.medium.terminate()

    def expired(self):
        '''@see: L{IAgentTask}'''

    @replay.immutable
    def finished(self, state):
        return state.medium.finished()


class StealthPeriodicTask(BaseTask):

    busy = False
    timeout = None

    def initiate(self, period):
        """
        @param period: the periodicity of the task, in seconds
        """
        self._period = period
        self._call = None
        self._canceled = False

        self._run()

        return NOT_DONE_YET

    def expired(self):
        self.cancel()

    @replay.immutable
    def cancel(self, state):
        if not self._canceled:
            self._canceled = True
            self._cancel()
            state.medium.terminate()

    def run(self):
        """Overridden in sub-classes. The time of the asynchronous job
        performed here is not subtracted from the period."""

    ### Private Methods ###

    def _run(self):
        d = defer.maybeDeferred(self.run)
        d.addErrback(defer.inject_param, 1, error.handle_failure, self,
                     "Failure during stealth task execution")
        d.addCallback(self._schedule)
        return d

    @replay.immutable
    def _cancel(self, state):
        if self._call is not None:
            state.medium.cancel_delayed_call(self._call)
            self._call = None

    @replay.immutable
    def _schedule(self, state, _=None):
        if self._canceled:
            return
        self._cancel()
        self._call = state.medium.call_later_ex(self._period,
                                                self._run,
                                                busy=False)


class LoopingCall(StealthPeriodicTask):

    def initiate(self, _period, _method, *args, **kwargs):
        self._method = _method
        self._args = args
        self._kwargs = kwargs
        return super(LoopingCall, self).initiate(_period)

    def run(self):
        return self._method(*self._args, **self._kwargs)
