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
import mock

from twisted.internet import defer, task

from feat.database import tools, document, migration, view, driver, client
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


class SimpleMigration(migration.Migration):

    def synchronous_hook(self, snapshot):
        snapshot['field1'] += " upgraded"
        return snapshot


class ComplexMigration(migration.Migration):

    def synchronous_hook(self, snapshot):
        snapshot['field1'] += " upgraded"
        return snapshot, dict(name='attachment', body='Hi!')

    def asynchronous_hook(self, connection, document, context):
        document.create_attachment(context['name'], context['body'])
        return connection.save_document(document)


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
    def testComplexMigration(self):
        migration.register(ComplexMigration(type_name=VersionedTest2.type_name,
                                            source_ver=1, target_ver=2))

        serialization.register(VersionedTest2)
        doc = yield self.connection.save_document(VersionedTest1())
        self.assertEqual('default', doc.field1)

        yield tools.migration_script(self.connection)
        self.assertTrue(self.run)

        doc = yield self.connection.get_document('testdoc')
        self.assertEqual('default upgraded', doc.field1)
        self.assertTrue('attachment' in doc.attachments)

    @defer.inlineCallbacks
    def testMigrating(self):
        serialization.register(VersionedTest1)
        feat.initial_data(VersionedTest1)
        yield tools.push_initial_data(self.connection)
        doc = yield self.connection.get_document('testdoc')
        self.assertEqual('default', doc.field1)

        serialization.register(VersionedTest2)
        migration.register(SimpleMigration(type_name=VersionedTest2.type_name,
                                           source_ver=1,
                                           target_ver=2))
        yield tools.migration_script(self.connection)

        doc = yield self.connection.get_document('testdoc')
        self.assertEqual('default upgraded', doc.field1)

    @defer.inlineCallbacks
    def testDefiningDocument(self):
        feat.initial_data(SomeDocument)
        feat.initial_data(
            SomeDocument(doc_id=u'special_id', field1=u'special'))

        yield tools.push_initial_data(self.connection)
        special = yield self.connection.get_document('special_id')
        self.assertIsInstance(special, SomeDocument)
        self.assertEqual('special', special.field1)
        ids = self.db._documents.keys()
        other_id = filter(lambda x: x not in ('special_id', "_design/feat",
                                              "_design/featjs"),
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


class SomeView(view.BaseView):

    name = "some_view"
    design_doc_id = "test_design_doc"

    def map(doc):
        yield None, True


class TestTriggeringViewUpdate(common.TestCase):

    configurable_attributes = ['views']

    views = [SomeView]

    def setUp(self):
        common.TestCase.setUp(self)

        self.connection = mock.Mock(spec=client.Connection)
        self.view_query_defers = list()
        self.connection.query_view = mock.Mock(side_effect=self._query_view)
        self.db = mock.Mock(spec=driver.Database)
        self.db.db_name = 'dbname'
        self.connection._database = self.db
        self.active_task_responses = list()
        self.db.couchdb_call = mock.Mock(side_effect=self._get_active_tasks)
        self.db.couchdb = mock.Mock(spec=driver.CouchDB)

        self.clock = task.Clock()

        ddoc = view.DesignDocument.generate_from_views(self.views)
        if ddoc:
            ddoc = ddoc[0]
        else:
            ddoc = view.DesignDocument(doc_id="test_design_doc")

        self.design_doc = ddoc

        self.task = tools.RebuildViewIndex(self.connection, self.design_doc)
        self.task.clock = self.clock

        # redirect log to testcase
        self.task._logger = self
        self.task.log_category = 'task'
        self.task.log_name = 'task'

    @defer.inlineCallbacks
    def testSuccessfulTrigger(self):
        d = self.task.start(1)
        query = self.view_query_defers[0]
        query.callback([])
        yield d

    @defer.inlineCallbacks
    def testFailToQuery(self):
        d = self.task.start(1)
        query = self.view_query_defers[0]
        query.errback(driver.DatabaseError('nope!'))

        self.assertFailure(d, driver.DatabaseError)

        yield d

    @defer.inlineCallbacks
    @common.attr(views=[])
    def testDocWithoutView(self):
        yield self.task.start(1)
        self.assertEqual(0, len(self.view_query_defers))

    @defer.inlineCallbacks
    def testHaveToWait(self):
        self.active_task_responses = [
            [# first run shows some progress
             {'type': 'indexer',
              'database': self.db.db_name,
              'design_document': self.design_doc.doc_id,
              'progress': 50},
             ],
            # seconf run shows no indexer
            [],
            ]

        d = self.task.start(1)
        query = self.view_query_defers[0]

        # no response consumed yet
        self.assertEqual(2, len(self.active_task_responses))

        self.clock.advance(1) # this should fire next iteration

        self.assertTrue(query.called) # should be cancelled
        self.assertIsNone(self.task.query_defer)
        # first response consumed
        self.assertEqual(1, len(self.active_task_responses))

        self.clock.advance(1) # this should fire third iteration
        query = self.view_query_defers[1]
        query.callback([])

        yield d

    def _get_active_tasks(self, method, location):
        assert method is self.db.couchdb.get, repr(method)
        assert location == '/_active_tasks', repr(location)

        return self.active_task_responses.pop(0)

    def _query_view(self, factory, **params):
        self.view_query_defers.append(defer.Deferred())
        return self.view_query_defers[-1]
