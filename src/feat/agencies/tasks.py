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
from twisted.python import failure
from zope.interface import implements

from feat.agents.base import replay
from feat.agencies import common, protocols
from feat.common import enum, defer, time, serialization
from feat.common import adapter

from feat.agencies.interface import IAgencyInitiatorFactory
from feat.agencies.interface import ILongRunningProtocol
from feat.interface.serialization import ISerializable
from feat.interface.task import NOT_DONE_YET, ITaskFactory, IAgencyTask


class TaskState(enum.Enum):
    '''
    performing - Task is running
    completed - Task is finished
    error - Task has an error
    expired - Task timeout
    terminated - Task terminated while performing
    '''

    performing, completed, expired, error, terminated = range(5)


class AgencyTask(common.AgencyMiddleBase):

    implements(ISerializable, IAgencyTask, ILongRunningProtocol)

    type_name = 'task-medium'

    error_state = TaskState.error # used by AgencyMiddleBase

    def __init__(self, agency_agent, factory, *args, **kwargs):
        common.AgencyMiddleBase.__init__(self, agency_agent, factory)

        self.task = None
        self.args = args
        self.kwargs = kwargs

    def call_later(self, *args, **kwargs):
        return self.agent.call_later(*args, **kwargs)

    def call_later_ex(self, *args, **kwargs):
        return self.agent.call_later_ex(*args, **kwargs)

    def cancel_delayed_call(self, call_id):
        return self.agent.cancel_delayed_call(call_id)

    ### ILongRunningProtocol ###

    def cancel(self):
        if self.factory.busy:
            # Busy task cannot be canceled
            return
        if self._finalize_called:
            # already finished (or cancelled)
            return
        d = self.call_agent_side(self.task.cancel)
        d.addBoth(self.finalize)
        return d

    ### IAgencyTask Methods ###

    def initiate(self):
        task = self.factory(self.agent.get_agent(), self)

        self.task = task
        self._set_state(TaskState.performing)

        if self.task.timeout:
            timeout = time.future(self.task.timeout)
            self.set_timeout(timeout, TaskState.expired, self._expired)

        self.call_agent_side(self._initiate, *self.args, **self.kwargs)

        return task

    ### IAgencyProtocolInternal Methods ###

    def get_agent_side(self):
        return self.task

    ### IAgencyTask ###

    @serialization.freeze_tag('AgencyTask.terminate')
    @replay.named_side_effect('AgencyTask.terminate')
    def terminate(self, arg=None):
        self._set_state(TaskState.completed)
        self.finalize(arg)

    @replay.named_side_effect('AgencyTask.fail')
    def fail(self, fail):
        if isinstance(fail, Exception):
            fail = failure.Failure(fail)
        self._set_state(self.error_state)
        self.finalize(fail)

    @replay.named_side_effect('AgencyTask.finished')
    def finished(self):
        return not self._cmp_state(TaskState.performing)

    ### ISerializable Methods ###

    def snapshot(self):
        return id(self)

    ### Private Methods ###

    def _initiate(self, *args, **kwargs):
        result = self.task.initiate(*args, **kwargs)
        if isinstance(result, defer.Deferred):
            result.addCallback(self._completed)
            return result
        self._completed(result)

    def _completed(self, arg):
        if arg != NOT_DONE_YET and self._cmp_state(TaskState.performing):
            self._set_state(TaskState.completed)
            self.finalize(arg)

    def _expired(self):
        error = self.create_expired_error(
            "Timeout of %d seconds exceeded waiting "
            "for task.initiate() to finish" % (self.task.timeout, ))
        self._set_state(TaskState.expired)
        d = self.call_agent_side(self.task.expired)
        d.addCallback(defer.drop_param, self.finalize, error)
        return d


@adapter.register(ITaskFactory, IAgencyInitiatorFactory)
class AgencyTaskFactory(protocols.BaseInitiatorFactory):
    type_name = 'task-medium-factory'
    protocol_factory = AgencyTask

    def __call__(self, agency_agent, *args, **kwargs):
        return self.protocol_factory(agency_agent, self._factory,
                                     *args, **kwargs)
