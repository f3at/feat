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
from feat.common import defer, log, first
from feat.agents.base import descriptor
from feat.agents.common import host
from feat.database import tools

from feat.database.interface import IDatabaseClient, NotFoundError


@defer.inlineCallbacks
def locate(connection, agent_id):
    '''
    Return the hostname of the agency where given agent runs or None.
    '''
    connection = IDatabaseClient(connection)
    log.log('locate', 'Locate called for agent_id: %r', agent_id)
    try:
        desc = yield connection.get_document(agent_id)
        log.log('locate', 'Got document %r', desc)
        if isinstance(desc, host.Descriptor):
            defer.returnValue(desc.hostname)
        elif isinstance(desc, descriptor.Descriptor):
            host_part = first(x for x in desc.partners if x.role == 'host')
            if host_part is None:
                log.log('locate',
                        'No host partner found in descriptor.')
                defer.returnValue(None)
            res = yield locate(connection, host_part.recipient.key)
            defer.returnValue(res)
    except NotFoundError:
        log.log('locate',
                'Host with id %r not found, returning None', agent_id)
        defer.returnValue(None)


def script():
    with tools.dbscript() as (d, args):

        @defer.inlineCallbacks
        def body(connection):
            if len(args) < 1:
                log.error('script', "USAGE: locate.py <agent_id>")
                return
            agent_id = args[0]
            try:
                host = yield locate(connection, agent_id)
            except Exception as e:
                log.error('script', 'ERROR: %r', e)
            log.info('script', 'Agent runs at host: %r', host)

        d.addCallback(body)
