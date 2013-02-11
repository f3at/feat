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
from zope.interface import implements, classProvides

from feat.agents.base import replay, task, poster, labour
from feat.agents.application import feat

from feat.agents.monitor.interface import IPacemakerFactory, IPacemaker
from feat.agents.monitor.interface import DEFAULT_HEARTBEAT_PERIOD
from feat.interface.agent import IAgent


@feat.register_restorator
class Pacemaker(labour.BaseLabour):

    classProvides(IPacemakerFactory)
    implements(IPacemaker)

    def __init__(self, patron, monitor, period=None):
        labour.BaseLabour.__init__(self, IAgent(patron))
        self._monitor = monitor
        self._period = period or DEFAULT_HEARTBEAT_PERIOD

    @replay.side_effect
    def startup(self):
        agent = self.patron

        self.debug("Starting agent %s pacemaker for monitor %s "
                   "with %s sec period",
                   agent.get_full_id(), self._monitor, self._period)

        poster = agent.initiate_protocol(HeartBeatPoster,
                                         self._monitor)
        agent.initiate_protocol(HeartBeatTask, poster, self._period)

    @replay.side_effect
    def cleanup(self):
        self.debug("Stopping agent %s pacemaker for monitor %s",
                   self.patron.get_full_id(), self._monitor)

    def __hash__(self):
        return hash(self._monitor)

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return True

    def __ne__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return False


@feat.register_restorator
class FakePacemaker(labour.BaseLabour):

    classProvides(IPacemakerFactory)
    implements(IPacemaker)

    def __init__(self, patron, monitor, period=None):
        labour.BaseLabour.__init__(self, IAgent(patron))

    @replay.side_effect
    def startup(self):
        """Nothing."""

    @replay.side_effect
    def cleanup(self):
        """Nothing."""


class HeartBeatPoster(poster.BasePoster):

    protocol_id = 'heart-beat'

    ### Overridden Methods ###

    @replay.immutable
    def pack_payload(self, state, index):
        desc = state.agent.get_descriptor()
        time = state.agent.get_time()
        return (desc.doc_id, time, index)


class HeartBeatTask(task.StealthPeriodicTask):

    protocol_id = "pacemaker:heart-beat"

    def initiate(self, poster, period):
        self._poster = poster
        self._index = 0
        return task.StealthPeriodicTask.initiate(self, period)

    def run(self):
        self._poster.notify(self._index)
        self._index += 1
