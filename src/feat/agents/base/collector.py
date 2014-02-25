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

from feat.common import log, defer, reflect, serialization, fiber
from feat.agents.base import replay
from feat.agencies import message
from feat.agents.application import feat

from feat.interface.protocols import *
from feat.interface.collector import *


class Meta(type(replay.Replayable)):

    implements(ICollectorFactory)

    def __init__(cls, name, bases, dct):
        cls.type_name = reflect.canonical_name(cls)
        cls.application.register_restorator(cls)
        super(Meta, cls).__init__(name, bases, dct)


class BaseCollector(log.Logger, replay.Replayable):

    __metaclass__ = Meta

    ignored_state_keys = ['medium', 'agent']

    implements(IAgentCollector)

    initiator = message.Notification
    interest_type = InterestType.private

    application = feat

    protocol_type = "Notification"
    protocol_id = None

    def __init__(self, agent, medium, *args, **kwargs):
        log.Logger.__init__(self, medium)
        replay.Replayable.__init__(self, agent, medium, *args, **kwargs)

    def init_state(self, state, agent, medium):
        state.agent = agent
        state.medium = medium

    @replay.immutable
    def restored(self, state):
        replay.Replayable.restored(self)
        log.Logger.__init__(self, state.medium)

    def initiate(self):
        '''@see: L{feat.interface.collector.IAgentCollector}'''

    def notified(self, notification):
        '''@see: L{feat.interface.collector.IAgentCollector}'''
