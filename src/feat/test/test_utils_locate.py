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
from feat.test import common
from feat.agents.common import host
from feat.agents.base import descriptor, agent
from feat.agencies import recipient
from feat.database import emu as database
from feat.utils.locate import locate
from feat.common import defer


class TestLocating(common.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        self.database = database.Database()
        self.connection = self.database.get_connection()

        host1 = host.Descriptor(doc_id=u'host1')
        host2 = host.Descriptor(doc_id=u'host2')
        self.host1 = yield self.connection.save_document(host1)
        self.host2 = yield self.connection.save_document(host2)
        part1 = agent.BasePartner(recipient.IRecipient(host1),
                                  role=u'host')
        agent1 = descriptor.Descriptor(partners=[part1])
        agent2 = descriptor.Descriptor()
        self.agent1 = yield self.connection.save_document(agent1)
        self.agent2 = yield self.connection.save_document(agent2)

    @defer.inlineCallbacks
    def testLocating(self):
        host1 = yield locate(self.connection, self.host1.doc_id)
        self.assertEqual('host1', host1)
        host1 = yield locate(self.connection, self.agent1.doc_id)
        self.assertEqual('host1', host1)
        none = yield locate(self.connection, self.agent2.doc_id)
        self.assertIs(None, none)
