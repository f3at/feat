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
import sys
import os

from feat.agents.base import agent, descriptor
from feat.agents.common import monitor
from feat.gateway.application import featmodels


class StandalonePartners(agent.Partners):

    default_role = u'standalone'


class DummyStandalone(agent.BaseAgent):

    partners_class = StandalonePartners

    standalone = True

    @staticmethod
    def get_cmd_line(desc):
        python_path = ":".join(sys.path)
        path = os.environ.get("PATH", "")

        command = 'feat'
        args = ['-X', '--agent-id', str(desc.doc_id)]
        env = dict(PYTHONPATH=python_path, FEAT_DEBUG='5', PATH=path)
        return command, args, env


class DummyAgent(agent.BaseAgent):

    pass


@featmodels.register_descriptor('dummy_buryme_standalone')
class DummyBuryMeStandaloneDescriptor(descriptor.Descriptor):
    pass


@featmodels.register_agent('dummy_buryme_standalone')
class DummyBuryMeStandalone(DummyStandalone):
    restart_strategy = monitor.RestartStrategy.buryme


@featmodels.register_descriptor('dummy_local_standalone')
class DummyLocalStandaloneDescriptor(descriptor.Descriptor):
    pass


@featmodels.register_agent('dummy_local_standalone')
class DummyLocalStandalone(DummyStandalone):
    restart_strategy = monitor.RestartStrategy.local


@featmodels.register_descriptor('dummy_wherever_standalone')
class DummyWhereverStandaloneDescriptor(descriptor.Descriptor):
    pass


@featmodels.register_agent('dummy_wherever_standalone')
class DummyWhereverStandalone(DummyStandalone):
    restart_strategy = monitor.RestartStrategy.wherever


@featmodels.register_descriptor('dummy_buryme_agent')
class DummyBuryMeAgentDescriptor(descriptor.Descriptor):
    pass


@featmodels.register_agent('dummy_buryme_agent')
class DummyBuryMeAgent(DummyAgent):
    restart_strategy = monitor.RestartStrategy.buryme


@featmodels.register_descriptor('dummy_local_agent')
class DummyLocalAgentDescriptor(descriptor.Descriptor):
    pass


@featmodels.register_agent('dummy_local_agent')
class DummyLocalAgent(DummyAgent):
    restart_strategy = monitor.RestartStrategy.local


@featmodels.register_descriptor('dummy_wherever_agent')
class DummyWhereverAgentDescriptor(descriptor.Descriptor):
    pass


@featmodels.register_agent('dummy_wherever_agent')
class DummyWhereverAgent(DummyAgent):
    restart_strategy = monitor.RestartStrategy.wherever
