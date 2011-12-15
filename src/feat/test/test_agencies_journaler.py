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
import signal
import tempfile
import os

from twisted.trial.unittest import FailTest, SkipTest

from feat.test import common
from feat.test.integration.common import ModelTestMixin
from feat.common import defer, time
from feat.agencies import journaler
from feat.common.serialization import banana
from feat.gateway import models


class SqliteWriter(journaler.SqliteWriter, common.Mock):

    def __init__(self, *args, **kwargs):
        common.Mock.__init__(self)
        journaler.SqliteWriter.__init__(self, *args, **kwargs)

    _create_schema = common.Mock.record(journaler.SqliteWriter._create_schema)


class DBTests(common.TestCase, ModelTestMixin):

    timeout = 2

    def setUp(self):
        common.TestCase.setUp(self)
        self.serializer = banana.Serializer()
        self.unserializer = banana.Unserializer()

    @defer.inlineCallbacks
    def testInitiateInMemory(self):
        jour = journaler.Journaler()
        writer = journaler.SqliteWriter(self)
        jour.configure_with(writer)

        self.assertEqual(journaler.State.connected,
                         jour._get_machine_state())

        self.assertEqual(journaler.State.disconnected,
                         writer._get_machine_state())

        yield writer.initiate()
        self.assertEqual(journaler.State.connected,
                         writer._get_machine_state())

        yield jour.close()
        self.assertEqual(journaler.State.disconnected,
                         jour._get_machine_state())

    @defer.inlineCallbacks
    def testStoringEntriesWhileDisconnected(self):
        jour = journaler.Journaler()
        writer = journaler.SqliteWriter(self, encoding='zip')
        num = 10
        defers = map(lambda _: jour.insert_entry(**self._generate_data()),
                     range(num))
        yield writer.initiate()
        yield jour.configure_with(writer)
        yield defer.DeferredList(defers)

        yield self._assert_entries(jour, num)

    @defer.inlineCallbacks
    def testStoringAndReadingEntries(self):
        jour = journaler.Journaler()
        writer = journaler.SqliteWriter(self, encoding='zip')
        yield writer.initiate()
        yield jour.configure_with(writer)

        yield jour.insert_entry(**self._generate_data())
        histories = yield writer.get_histories()
        self.assertIsInstance(histories, list)
        self.assertIsInstance(histories[0], journaler.History)

        entries = yield writer.get_entries(histories[0])
        self.assertIsInstance(entries, list)
        self.assertEqual(1, len(entries))
        unpacked = entries[0]
        self.assertEqual('some id', unpacked['agent_id'])
        self.assertEqual('some.canonical.name', unpacked['function_id'])
        self.assertEqual(('some_id', 1, 0, ),
                         self.unserializer.convert(unpacked['journal_id']))
        self.assertEqual(None,
                         self.unserializer.convert(unpacked['result']))
        self.assertEqual(list(),
                         self.unserializer.convert(unpacked['side_effects']))

        yield jour.insert_entry(**self._generate_data(function_id='other'))
        entries = yield writer.get_entries(histories[0])
        self.assertEqual(2, len(entries))
        first = entries[0]
        second = entries[1]
        self.assertEqual('some.canonical.name', first['function_id'])
        self.assertEqual('other', second['function_id'])

    @defer.inlineCallbacks
    def testInitiateOnDisk(self):
        filename = self._get_tmp_file()
        jour = journaler.Journaler()
        writer = SqliteWriter(self, filename=filename)
        yield writer.initiate()
        yield jour.configure_with(writer)
        self.assertCalled(writer, '_create_schema', times=1)
        self.assertEqual(journaler.State.connected,
                         jour._get_machine_state())
        self.assertEqual(journaler.State.connected,
                         writer._get_machine_state())
        yield writer.close()
        self.assertEqual(journaler.State.disconnected,
                         writer._get_machine_state())
        self.assertEqual(journaler.State.connected,
                         jour._get_machine_state())
        yield writer.initiate()
        self.assertEqual(journaler.State.connected,
                         writer._get_machine_state())
        yield jour.close()
        yield writer.close()
        self.assertCalled(writer, '_create_schema', times=1)

    @defer.inlineCallbacks
    def testLoadingCorrectEncoding(self):
        filename = self._get_tmp_file()

        writer = SqliteWriter(self, filename=filename, encoding='zip')
        yield writer.initiate()
        yield writer.close()

        writer = SqliteWriter(self, filename=filename, encoding='sth else')
        yield writer.initiate()
        # stored value should win
        self.assertEqual('zip', writer._encoding)

    @defer.inlineCallbacks
    @common.attr(timeout=10)
    def testJourfileRotation(self):
        self._rotate_called = 0

        def on_rotate():
            self._rotate_called += 1

        filename = self._get_tmp_file()
        jour = journaler.Journaler(on_rotate_cb=on_rotate)
        writer = journaler.SqliteWriter(
            self, filename=filename, encoding='zip')
        yield writer.initiate()
        d = jour.insert_entry(**self._generate_data())
        yield jour.configure_with(writer)
        yield d
        yield self._assert_entries(jour, 1)

        ourpid = os.getpid()

        # now rotate the journal 3 times
        for x in range(3):
            newname = self._get_tmp_file()
            os.rename(filename, newname)
            os.kill(ourpid, signal.SIGHUP)

            yield self._assert_entries(jour, 0)
            yield jour.insert_entry(**self._generate_data())
            yield self._assert_entries(jour, 1)

            self.assertTrue(os.path.exists(filename))
            self.assertTrue(os.path.exists(newname))

        self.assertEqual(4, self._rotate_called)
        yield jour.close()

    @common.attr(timeout=30)
    @defer.inlineCallbacks
    def testMisconfiguredPostgresFallbackToSqlite(self):
        try:
            import txpostgres
        except ImportError:
            raise SkipTest('txpostgres package is missing')
        postgres = ('postgres://%s:%s@%s/%s' %
                    ('user', 'password', 'localhost', 'name'))
        tmpfile = self._get_tmp_file()
        sqlite = 'sqlite://' + tmpfile
        connstrs = [postgres, sqlite]
        jour = journaler.Journaler()
        jour.set_connection_strings(connstrs)
        jour.insert_entry(**self._generate_data())

        @defer.inlineCallbacks
        def check():
            w = jour._writer
            self.log('writer is %r', w)
            if isinstance(w, journaler.SqliteWriter):
                try:
                    num = yield self._get_number_of_entries(jour, 1)
                    self.log('num is %d', num)
                    defer.returnValue(num == 1)
                except FailTest, e:
                    self.log('assertation failure: %r', e)
                    defer.returnValue(False)
                defer.returnValue(True)
            defer.returnValue(False)

        yield self.wait_for(check, 20)
        self.assertTrue(os.path.exists(tmpfile))

        yield jour.insert_entry(**self._generate_data())
        yield self._assert_entries(jour, 2)

        # now validate the model display
        yield self.validate_model_tree(models.Journaler(jour))

        yield jour.close()
        import psycopg2
        self.flushLoggedErrors(psycopg2.OperationalError)

    @common.attr(timeout=15)
    @defer.inlineCallbacks
    def testMigratingEntries(self):
        writer = journaler.SqliteWriter(self)
        data = [self._generate_data() for x in range(2400)]
        data += [self._generate_log() for x in range(200)]
        yield writer.initiate()
        yield writer.insert_entries(data)

        jour = journaler.Journaler()
        jour.set_connection_strings(['sqlite://' + self._get_tmp_file()])

        yield jour.migrate_entries(writer)
        yield self._assert_entries(jour, 2400)
        yield self._assert_entries(writer, 0)

        logs = yield writer.get_log_entries()
        self.assertEqual(0, len(logs))
        logs = yield jour._writer.get_log_entries()
        # we have some extra logs comming from normal logging
        self.assertTrue(len(logs) > 200)
        yield writer.close()

    def _get_tmp_file(self):
        fd, name = tempfile.mkstemp(suffix='_journal.sqlite')
        self.addCleanup(os.remove, name)
        return name

    def _generate_log(self, **opts):
        defaults = {
            'entry_type': 'log',
            'message': 'Some log message',
            'level': 2,
            'category': 'feat',
            'log_name': None,
            'file_path': __file__,
            'line_num': 100,
            'timestamp': int(time.time())}

        defaults.update(opts)
        return defaults

    def _generate_data(self, **opts):
        defaults = {
            'entry_type': 'journal',
            'agent_id': 'some id',
            'instance_id': 1,
            'journal_id': self.serializer.convert(('some_id', 1, 0, )),
            'function_id': 'some.canonical.name',
            'args': self.serializer.convert(tuple()),
            'kwargs': self.serializer.convert(dict()),
            'fiber_id': 'some fiber id',
            'fiber_depth': 1,
            'result': self.serializer.convert(None),
            'side_effects': self.serializer.convert(list()),
            'timestamp': int(time.time())}

        defaults.update(opts)
        return defaults

    @defer.inlineCallbacks
    def _assert_entries(self, jour, expected):
        num = yield self._get_number_of_entries(jour, expected)
        self.assertEqual(expected, num)

    @defer.inlineCallbacks
    def _get_number_of_entries(self, jour, num):
        if isinstance(jour, journaler.Journaler):
            writer = jour._writer
        else:
            writer = jour
        histories = yield writer.get_histories()
        self.assertIsInstance(histories, list)
        self.assertTrue(len(histories) > 0)
        if num > 0:
            self.assertIsInstance(histories[0], journaler.History)
            entries = yield writer.get_entries(histories[0])
            self.assertIsInstance(entries, list)
            defer.returnValue(len(entries))
        else:
            defer.returnValue(0)


class TestParsingConnection(common.TestCase):

    def testItWorks(self):
        klass, params = journaler.parse_connstr(
            'sqlite:///var/log/journal.sqlite3')
        self.assertEqual(journaler.SqliteWriter, klass)
        self.assertEqual('/var/log/journal.sqlite3', params['filename'])
        self.assertEqual('zip', params['encoding'])

        klass, params = journaler.parse_connstr(
            'postgres://feat:feat@flt1.somecluster.lt.net/feat')
        self.assertEqual(journaler.PostgresWriter, klass)
        self.assertEqual('feat', params['user'])
        self.assertEqual('feat', params['password'])
        self.assertEqual('flt1.somecluster.lt.net', params['host'])
        self.assertEqual('feat', params['database'])
