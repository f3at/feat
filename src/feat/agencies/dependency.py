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
from feat.common import enum
from feat.agents.base import replay
from feat.interface.agency import ExecMode


class AgencyDependencyMixin(object):

    def __init__(self, default):
        self._dependencies_modes = dict()
        self._set_default_mode(default)

    def _set_default_mode(self, default):
        self._dependencies_modes['_default'] = default

    def set_mode(self, component, mode):
        assert isinstance(mode, ExecMode)
        self._dependencies_modes[component] = mode

    def get_mode(self, component):
        return self._dependencies_modes.get(component,
                                        self._dependencies_modes['_default'])


class AgencyAgentDependencyMixin(object):

    keeps_track_of_dependencies = False

    @replay.named_side_effect('AgencyAgent.get_mode')
    def get_mode(self, component):
        return self.agency.get_mode(component)
