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
from feat.agents.base import agent, replay, descriptor
from feat.agents.common import raage
from feat.common import manhole
from feat.agents.application import feat


@feat.register_agent('requesting_agent')
class RequestingAgent(agent.BaseAgent):

    @manhole.expose()
    @replay.mutable
    def request_resource(self, state, resources, categories, agent_id=None):
        self.info('Requesting resoruce %r category %r', resources, categories)
        return raage.allocate_resource(self, resources, categories=categories,
                                       agent_id=agent_id)

    @manhole.expose()
    @replay.mutable
    def request_local_resource(self, state, resources, categories):
        self.info('Requesting resoruce %r category %r', resources, categories)
        return raage.allocate_resource(self, resources, categories=categories,
                                       max_distance=0)


@feat.register_descriptor('requesting_agent')
class Descriptor(descriptor.Descriptor):
    pass
