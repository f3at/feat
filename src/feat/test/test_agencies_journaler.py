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
import uuid

from twisted.trial.unittest import FailTest, SkipTest

from feat.test import common
from feat.test.integration.common import ModelTestMixin
from feat.common import defer, time, error, log, manhole, first
from feat.agencies import journaler
from feat.agencies.net import broker
from feat.common.serialization import banana
from feat.gateway import models


class GenerateEntryMixin(object):

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

        r = dict(defaults)
        r.update(opts)
        return r

    def _generate_entry(self, **opts):
        if not hasattr(self, 'serializer'):
            self.serializer = banana.Serializer()

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

        r = dict(defaults)
        r.update(opts)
        return r


class SqliteWriter(journaler.SqliteWriter, common.Mock):

    def __init__(self, *args, **kwargs):
        common.Mock.__init__(self)
        journaler.SqliteWriter.__init__(self, *args, **kwargs)

    _create_schema = common.Mock.record(journaler.SqliteWriter._create_schema)


class DBTests(common.TestCase, ModelTestMixin, GenerateEntryMixin):

    timeout = 2

    def setUp(self):
        common.TestCase.setUp(self)

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
        defers = map(lambda _: jour.insert_entry(**self._generate_entry()),
                     range(num))
        yield writer.initiate()
        yield jour.configure_with(writer)
        yield defer.DeferredList(defers)

        yield self._assert_entries(jour, num)

    @defer.inlineCallbacks
    def testStoringUnicodeMamboJambo(self):
        jour = journaler.Journaler()
        writer = journaler.SqliteWriter(self, encoding='zip')

        yield writer.initiate()
        yield jour.configure_with(writer)
        troublemaker = 'Jim\xc3\xa9nez'.decode('iso-8859-1')
        yield jour.insert_entry(**self._generate_log(
            message=troublemaker))

        log_entries = yield writer.get_log_entries()
        self.assertEqual(1, len(log_entries))
        self.assertEqual('Jim??nez', log_entries[0]['message'])

    @defer.inlineCallbacks
    def testStoringAndReadingEntries(self):
        jour = journaler.Journaler()
        writer = journaler.SqliteWriter(self, encoding='zip')

        yield writer.initiate()
        yield jour.configure_with(writer)
        yield jour.insert_entry(**self._generate_entry())
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
                         banana.unserialize(unpacked['journal_id']))
        self.assertEqual(None,
                         banana.unserialize(unpacked['result']))
        self.assertEqual(list(),
                         banana.unserialize(unpacked['side_effects']))

        yield jour.insert_entry(**self._generate_entry(function_id='other'))
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
        d = jour.insert_entry(**self._generate_entry())
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
            yield jour.insert_entry(**self._generate_entry())
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
        agency_stub = AgencyStub()
        jour = journaler.Journaler(
            on_switch_writer_cb=agency_stub.on_switch_writer)
        jour.set_connection_strings(connstrs)
        jour.insert_entry(**self._generate_entry())

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

        self.assertEqual([0, 1], agency_stub.calls)

        yield jour.insert_entry(**self._generate_entry())
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
        data = [self._generate_entry() for x in range(2400)]
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
        # we might have some extra logs comming from normal logging
        # in case we run with FEAT_DEBUG >=3
        self.assertTrue(len(logs) >= 200)
        yield writer.close()

    def _get_tmp_file(self):
        fd, name = tempfile.mkstemp(suffix='_journal.sqlite')
        self.addCleanup(os.remove, name)
        return name

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


class TestSqliteAsIJournalReader(common.TestCase, GenerateEntryMixin):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)

        self.hostname = 'hostname'
        self.writer = journaler.SqliteWriter(
            self, encoding='zip', hostname=self.hostname)
        self.reader = self.writer
        yield self.writer.initiate()

    @defer.inlineCallbacks
    def _populate_data(self):
        e = self._generate_entry
        l = self._generate_log

        self.now = time.time()
        self.past1 = self.now - 100
        self.past2 = self.past1 - 100

        yield self.writer.insert_entries([
            e(agent_id='other_agent', args='some args', timestamp=self.past1),
            e(agent_id='other_agent'),
            e(),
            e(),
            l(level=2, category='test', log_name='log_name',
              timestamp=self.past2, message='m1'),
            l(level=1, category='test', timestamp=self.past1, message='m2'),
            l(level=1, message='m3'),
            l(level=2, message='m4')])

    @defer.inlineCallbacks
    def testGettingJournalerEntries(self):
        yield self._populate_data()

        # test getting histories
        histories = yield self.reader.get_histories()
        self.assertEqual(2, len(histories))
        self.assertEqual('other_agent', histories[0].agent_id)
        self.assertEqual('some id', histories[1].agent_id)
        self.assertEqual(1, histories[0].instance_id)
        self.assertEqual(1, histories[1].instance_id)
        self.assertEqual(self.hostname, histories[0].hostname)
        self.assertEqual(self.hostname, histories[1].hostname)

        # get entris for history
        entries = yield self.reader.get_entries(histories[0])
        self.assertEqual(2, len(entries))
        self.assertEqual('some args', entries[0]['args'])

        # same with start_date
        entries = yield self.reader.get_entries(histories[0],
                                                start_date=self.now-10)
        self.assertEqual(1, len(entries))
        self.assertEqual(tuple(), banana.unserialize(entries[0]['args']))

        # same with limit on number
        entries = yield self.reader.get_entries(histories[0], limit=1)
        self.assertEqual(1, len(entries))
        self.assertEqual('some args', entries[0]['args'])

        # getting bare entries
        entries = yield self.reader.get_bare_journal_entries()
        self.assertEqual(4, len(entries))
        self.assertEqual('other_agent', entries[0]['agent_id'])
        self.assertEqual('other_agent', entries[1]['agent_id'])

        # deleting entries
        yield self.reader.delete_top_journal_entries(2)
        entries = yield self.reader.get_bare_journal_entries()
        self.assertEqual(2, len(entries))
        self.assertEqual('some id', entries[0]['agent_id'])
        self.assertEqual('some id', entries[1]['agent_id'])

    @defer.inlineCallbacks
    def testQueryingLogNamesHostsAndCategories(self):
        yield self._populate_data()

        # test getting time boundaries
        # tolerance of 1 seconds is due to converting float timestamp to int
        start, end = yield self.reader.get_log_time_boundaries()
        self.assertApproximates(self.past2, start, 1)
        self.assertApproximates(self.now, end, 1)

        # query available hostnames
        hosts = yield self.reader.get_log_hostnames()
        self.assertEqual([self.hostname], hosts)

        #test getting categories
        categories = yield self.reader.get_log_categories()
        self.assertEqual(set(['feat', 'test']), set(categories))

        # now limited for host (it this case its just ignored)
        categories = yield self.reader.get_log_categories(
            hostname=self.hostname)
        self.assertEqual(set(['feat', 'test']), set(categories))

        #now with time conditions
        categories = yield self.reader.get_log_categories(
            start_date=self.now-10)
        self.assertEqual(set(['feat']), set(categories))
        categories = yield self.reader.get_log_categories(end_date=self.now-10)
        self.assertEqual(set(['test']), set(categories))

        #test getting log names
        names = yield self.reader.get_log_names('test')
        self.assertEqual(2, len(names))
        self.assertEqual(set([None, 'log_name']), set(names))

        names = yield self.reader.get_log_names('test',
                                                start_date=self.past1-10)
        self.assertEqual(1, len(names))
        self.assertEqual([None], names)
        names = yield self.reader.get_log_names('test',
                                                end_date=self.past1-10)
        self.assertEqual(1, len(names))
        self.assertEqual(['log_name'], names)

        # unknown category
        names = yield self.reader.get_log_names('unknown')
        self.assertEqual([], names)

    @defer.inlineCallbacks
    def testGettingLogEntries(self):
        yield self._populate_data()

        # simple query
        entries = yield self.reader.get_log_entries()
        self.assertEqual(4, len(entries))

        # with time condition
        entries = yield self.reader.get_log_entries(start_date=self.now-10)
        self.assertEqual(2, len(entries))
        self.assertEqual('m3', entries[0]['message'])
        self.assertEqual('m4', entries[1]['message'])

        entries = yield self.reader.get_log_entries(end_date=self.now-10)
        self.assertEqual(2, len(entries))
        self.assertEqual('m1', entries[0]['message'])
        self.assertEqual('m2', entries[1]['message'])

        # filter by category
        entries = yield self.reader.get_log_entries(
            filters=[dict(category='test', level=5)])
        self.assertEqual(2, len(entries))
        self.assertEqual('m1', entries[0]['message'])
        self.assertEqual('m2', entries[1]['message'])

        # category and time conditions
        # filter by category
        entries = yield self.reader.get_log_entries(
            filters=[dict(category='test', level=5)],
            start_date=self.now-10)
        self.assertEqual(0, len(entries))

        entries = yield self.reader.get_log_entries(
            filters=[dict(category='test', level=5)],
            end_date=self.now-10)
        self.assertEqual(2, len(entries))

        # filter by name and category
        entries = yield self.reader.get_log_entries(
            filters=[dict(category='test', level=5, name='log_name')])
        self.assertEqual(1, len(entries))
        self.assertEqual('m1', entries[0]['message'])

        # filter by level
        entries = yield self.reader.get_log_entries(
            filters=[dict(category='test', level=1)])
        self.assertEqual(1, len(entries))
        self.assertEqual('m2', entries[0]['message'])

        # deleting top entries
        yield self.reader.delete_top_log_entries(2)

        # only 2 entries left
        entries = yield self.reader.get_log_entries()
        self.assertEqual(2, len(entries))

        # now category test should be gone
        categories = yield self.reader.get_log_categories()
        self.assertEqual(['feat'], categories)

    @defer.inlineCallbacks
    def tearDown(self):
        yield self.writer.close()
        yield common.TestCase.tearDown(self)


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

        self.assertRaises(error.FeatError, journaler.parse_connstr,
                          'sqlite3://mistyped.sqlite3')


class AgencyStub(object):

    def __init__(self):
        self.calls = list()

    def on_switch_writer(self, index):
        self.calls.append(index)


class DummyAgency(log.LogProxy, manhole.Manhole, log.Logger):

    log_category = 'dummy_agency'

    def __init__(self, testcase):
        log.Logger.__init__(self, testcase)
        log.LogProxy.__init__(self, testcase)
        self.agency_id = str(uuid.uuid1())

        self._journaler = journaler.Journaler(self)
        self.broker = broker.Broker(self)

    @property
    def journaler(self):
        return self._journaler

    def iter_agents(self):
        # used by broker initialization
        return iter([])


class TestWritingEntriesThroughBrokerConnection(
    common.TestCase, GenerateEntryMixin):

    timeout=10

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)

        self.agencies = [DummyAgency(self) for x in range(2)]
        self.brokers = [x.broker for x in self.agencies]
        self.journalers = [x.journaler for x in self.agencies]
        self._delete_socket_file()

        yield self.brokers[0].initiate_broker()
        yield self.brokers[1].initiate_broker()

        self.sql_writer = journaler.SqliteWriter(self)
        yield self.sql_writer.initiate()
        self.journalers[0].configure_with(self.sql_writer)

        self.broker_writer = journaler.BrokerProxyWriter(self.brokers[1])
        yield self.broker_writer.initiate()
        self.journalers[1].configure_with(self.broker_writer)

    @defer.inlineCallbacks
    def testStoringEntries(self):
        l = self._generate_log
        e = self._generate_entry

        yield self.journalers[1].insert_entries([
            l(message="some cool msg"),
            e(agent_id='standalone_agent')])
        histories = yield self.sql_writer.get_histories()
        self.assertEqual(1, len(histories))
        self.assertEqual('standalone_agent', histories[0].agent_id)

        logs = yield self.sql_writer.get_log_entries()
        self.assertTrue(first(x for x in logs
                              if x['message'] == 'some cool msg'))

    @defer.inlineCallbacks
    def tearDown(self):
        for x in self.journalers:
            yield x.close(False)
        for x in self.brokers:
            yield x.disconnect()
        yield common.TestCase.tearDown(self)

    def _delete_socket_file(self):
        try:
            os.unlink(self.brokers[0].socket_path)
        except OSError:
            pass
