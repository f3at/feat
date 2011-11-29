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

'''
This is empty module which is supposed to import all the modules which declare
agents, descriptors, things which needs to be declared.
'''

from feat.agents.host import host_agent
from feat.agents.shard import shard_agent
from feat.agents.raage import raage_agent
from feat.agents.dns import dns_agent
from feat.agents.monitor import monitor_agent
from feat.agents.alert import alert_agent
from feat.agents.export import export_agent
from feat.agents.migration import migration_agent
from feat.agents.common import host, shard, raage, dns, monitor, export

# Internal to register serialization adapters
from feat.common.serialization import adapters

# Internal imports for agency
from feat.agencies import contracts, requests, tasks, notifications

# Imports for gateway
from feat.gateway import models, dummies
