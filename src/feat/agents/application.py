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

from feat import applications


class Feat(applications.Application):

    name = 'feat'
    version = '0.23.0'
    module_prefixes = ['feat.agents']
    loadlist = [
        'feat.agents.host.host_agent',
        'feat.agents.host.api',
        'feat.agents.shard.shard_agent',
        'feat.agents.raage.raage_agent',
        'feat.agents.dns.dns_agent',
        'feat.agents.monitor.monitor_agent',
        'feat.agents.alert.alert_agent',
        'feat.agents.nagios.nagios_agent',
        'feat.agents.integrity.integrity_agent',
        'feat.agents.integrity.api',
        'feat.agents.common.host',
        'feat.agents.common.shard',
        'feat.agents.common.raage',
        'feat.agents.common.dns',
        'feat.agents.common.monitor',
        'feat.agents.common.nagios',
        ]


feat = Feat()
