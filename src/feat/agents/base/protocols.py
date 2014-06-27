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

from feat.agents.base import replay
from feat.common import log, fiber, defer, serialization

from feat.agencies.interface import IAgencyInitiatorFactory
from feat.interface.protocols import IAgentProtocol, ProtocolCancelled
from feat.interface.protocols import IInitiatorFactory, IInterested
from feat.interface.protocols import IInitiator


class BaseProtocol(log.Logger, replay.Replayable):

    implements(IAgentProtocol)

    ignored_state_keys = ['medium', 'agent']

    protocol_type = None
    protocol_id = None

    def __init__(self, agent, medium):
        log.Logger.__init__(self, medium)
        replay.Replayable.__init__(self, agent, medium)

    @replay.immutable
    def restored(self, state):
        replay.Replayable.restored(self)
        log.Logger.__init__(self, state.medium)

    def init_state(self, state, agent, medium):
        state.agent = agent
        state.medium = medium

    ### public ###

    @replay.immutable
    def fiber_new(self, state):
        return fiber.Fiber(canceller=state.medium.get_canceller(),
                           debug_depth=2)

    @replay.immutable
    def fiber_succeed(self, state, param=None):
        return fiber.succeed(param, canceller=state.medium.get_canceller(),
                             debug_depth=2)

    @replay.immutable
    def fiber_fail(self, state, failure):
        return fiber.fail(failure, canceller=state.medium.get_canceller(),
                          debug_depth=2)

    ### IAgentProtocol ###

    def initiate(self):
        '''@see: L{contractor.IAgentContractor}'''

    @replay.immutable
    def cancel(self, state):
        return state.medium._terminate(ProtocolCancelled())

    @replay.immutable
    def is_idle(self, state):
        return state.medium.is_idle()


class BaseInitiator(BaseProtocol):

    implements(IInitiator)

    @replay.journaled
    def notify_state(self, state, *states):
        return fiber.wrap_defer_ex(state.medium.wait_for_state,
                                   states, debug_depth=2)

    @replay.journaled
    def notify_finish(self, state):
        return fiber.wrap_defer_ex(state.medium.notify_finish, debug_depth=2)

    @replay.immutable
    def get_expiration_time(self, state):
        return state.medium.get_expiration_time()


class BaseInterested(BaseProtocol):

    implements(IInterested)

    initiator = None
    interest_type = None

    @replay.immutable
    def get_expiration_time(self, state):
        return state.medium.get_expiration_time()


class Singleton(serialization.Serializable):
    '''
    To be used like:

      factory = Singleton(SomeOtherFactory, min_delay_between_runs=5)
      ...
      agent.initiate_protocol(factory, *args, **kwargs)

    This will ensure that only one instance of this task runs at the time.
    Any call done while the task is running will be ignored.

    Additionally this factory can specify the minimum time that has to
    pass between subsequent runs of the task. If its specified, the
    execution of the next run is scheduleged in future instead of
    being performed right away.
    '''

    implements(IInitiatorFactory, IAgencyInitiatorFactory)

    def __init__(self, factory, min_delay_between_runs=0):
        self._min_delay_between_runs = min_delay_between_runs

        self.factory = IInitiatorFactory(factory)

        self._next_run_epoch = None
        self._agency_agent = None
        self._medium = None

    ### IInitiatorFactory ###

    @property
    def protocol_id(self):
        return 'singleton-' + self.factory.protocol_id

    @property
    def protocol_type(self):
        return self.factory.protocol_type

    ### IAgencyProtocolInternal ###

    def notify_finish(self):
        return self._medium.notify_finish()

    def initiate(self):
        ctime = self._agency_agent.get_time()
        if (self._next_run_epoch is None or
            ctime > self._next_run_epoch):
            return self._medium.initiate()
        else:
            remaining = self._next_run_epoch - ctime
            self._agency_agent.debug(
                "Scheduling execution of %s.%s protocol %s in seconds",
                self.factory.protocol_type, self.factory.protocol_id,
                remaining)
            self._agency_agent.call_later(remaining, self._medium.initiate)
            return

    @property
    def guid(self):
        return self._medium.guid

    def cleanup(self):
        return self._medium.cleanup()

    def get_agent_side(self):
        return self._medium.get_agent_side()

    ### IAgencyInitiatorFactory ###

    def __call__(self, agency_agent, *args, **kwargs):
        self._agency_agent = agency_agent
        if self._medium is not None:
            self._agency_agent.log(
                'Singleton protocol %s.%s is currently running. '
                'Refusing running another instance',
                self.factory.protocol_type,
                self.factory.protocol_id)
            return

        medium_factory = IAgencyInitiatorFactory(self.factory)
        self._medium = medium_factory(agency_agent, *args, **kwargs)
        self._medium.notify_finish().addBoth(defer.drop_param,
                                             self._run_finished)

        return self

    ### private ###

    def _run_finished(self):
        ctime = self._agency_agent.get_time()
        self._next_run_epoch = ctime + self._min_delay_between_runs
        self._medium = None
