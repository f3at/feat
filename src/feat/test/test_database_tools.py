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
from twisted.internet import defer

from feat.database import tools, document
from feat.test import common
from feat.test.integration.common import SimulationTest
from feat.common import serialization
from feat.agents.application import feat
from feat import applications


@serialization.register
class SomeDocument(document.Document):

    type_name = 'spam'
    document.field('doc_id', 'somedoc', '_id')
    document.field('field1', u'default')


class VersionedTest1(document.VersionedDocument):

    version = 1
    type_name = 'version-document-test'

    document.field('doc_id', 'testdoc', '_id')
    document.field('field1', u'default')


class VersionedTest2(VersionedTest1):

    version = 2
    type_name = 'version-document-test'

    @classmethod
    def upgrade_to_2(cls, snapshot):
        snapshot['field1'] += " upgraded"
        return snapshot


class TestCase(common.TestCase, common.AgencyTestHelper):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.AgencyTestHelper.setUp(self)
        self.db = self.agency._database
        self.connection = self.db.get_connection()
        r = applications.get_initial_data_registry()
        snapshot = r.get_snapshot()
        self.addCleanup(r.reset, snapshot)
        r.reset([])

    @defer.inlineCallbacks
    def testMigrating(self):
        serialization.register(VersionedTest1)
        feat.initial_data(VersionedTest1)
        yield tools.push_initial_data(self.connection)
        doc = yield self.connection.get_document('testdoc')
        self.assertEqual('default', doc.field1)

        serialization.register(VersionedTest2)
        yield tools.migration_script(self.connection)

        doc = yield self.connection.get_document('testdoc')
        self.assertEqual('default upgraded', doc.field1)

    @defer.inlineCallbacks
    def testDefiningDocument(self):
        feat.initial_data(SomeDocument)
        feat.initial_data(
            SomeDocument(doc_id=u'special_id', field1=u'special'))

        yield tools.push_initial_data(self.connection)
        # 3 = 2 (registered documents) + 1 (design document)
        self.assertEqual(3, len(self.db._documents))
        special = yield self.connection.get_document('special_id')
        self.assertIsInstance(special, SomeDocument)
        self.assertEqual('special', special.field1)
        ids = self.db._documents.keys()
        other_id = filter(lambda x: x not in ('special_id', "_design/feat"),
                          ids)[0]
        normal = yield self.connection.get_document(other_id)
        self.assertEqual('default', normal.field1)

    def testRevertingDocuments(self):
        old = tools.get_current_initials()
        feat.initial_data(SomeDocument)
        current = tools.get_current_initials()
        self.assertEqual(len(old) + 1, len(current))
        tools.reset_documents(old)
        current = tools.get_current_initials()
        self.assertEqual(len(old), len(current))


class IntegrationWithSimulation(SimulationTest):

    def setUp(self):
        feat.initial_data(SomeDocument)
        return SimulationTest.setUp(self)

    def testItWorks(self):
        pass

    @defer.inlineCallbacks
    def tearDown(self):
        yield SimulationTest.tearDown(self)
        current = tools.get_current_initials()
        self.assertFalse(isinstance(current[-1], SomeDocument))
