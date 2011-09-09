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
from feat.common import log, fiber

from feat.interface.protocols import *


class BaseProtocol(log.Logger, replay.Replayable):

    implements(IAgentProtocol)

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
        return fiber.wrap_defer(state.medium.wait_for_state, *states)

    @replay.journaled
    def notify_finish(self, state):
        return fiber.wrap_defer(state.medium.notify_finish)

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
