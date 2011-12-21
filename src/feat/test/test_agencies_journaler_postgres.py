import os

from twisted.trial.unittest import SkipTest

from feat.agencies import journaler
from feat.common import defer, time
from feat.common.serialization import banana
from feat.gateway import models
from feat.test import common
from feat.test.integration.common import ModelTestMixin

from feat.test.test_agencies_journaler import GenerateEntryMixin


psycopg2 = None
try:
    import psycopg2
    import psycopg2.extensions
except ImportError:
    pass


DB_NAME = os.environ.get('FEAT_TEST_PG_NAME', "feat_test")
DB_HOST = os.environ.get('FEAT_TEST_PG_HOST', "localhost")
DB_USER = os.environ.get('FEAT_TEST_PG_USER', "feat_test")
DB_PASSWORD = os.environ.get('FEAT_TEST_PG_PASSWORD', "feat_test")


def getSkipForPsycopg2():
    if not psycopg2:
        return "psycopg2 not installed"
    try:
        psycopg2.extensions.POLL_OK
    except AttributeError:
        return ("psycopg2 does not have async support. "
                "You need at least version 2.2.0 of psycopg2 "
                "to use txpostgres.")
    try:
        psycopg2.connect(user=DB_USER, password=DB_PASSWORD,
                         host=DB_HOST, database=DB_NAME).close()
    except psycopg2.Error, e:
        return ("cannot connect to test database %r "
                "using host %r, user %r, password: %r, %s" %
                (DB_NAME, DB_HOST, DB_USER, DB_PASSWORD, e))
    return None


_skip = getSkipForPsycopg2()


class PostgresTestMixin(object):

    skip = _skip

    def setUp(self):
        self.connection = psycopg2.connect(
            user=DB_USER, password=DB_PASSWORD,
            host=DB_HOST, database=DB_NAME)
        self.cursor = self.connection.cursor()

        # prepare schema
        path = os.path.normpath(os.path.join(os.path.basename(__file__),
                            '..', '..', '..', 'conf', 'postgres',
                            'schema.pgsql'))
        if not os.path.exists(path):
            raise SkipTest("Schema file %s doesn't exist" % (path, ))
        schema = file(path).read()
        self.info('Executing schema script: \n%s', schema)
        self.cursor.execute('begin')
        self.cursor.execute(schema)
        self.cursor.execute('commit')


class TestPostgressReader(common.TestCase, GenerateEntryMixin,
                          PostgresTestMixin):

    @defer.inlineCallbacks
    def setUp(self):
        common.TestCase.setUp(self)
        PostgresTestMixin.setUp(self)

        self.hostname = 'hostname'
        self.writer = journaler.PostgresWriter(
            self, user=DB_USER, host=DB_HOST,
            database=DB_NAME,
            password=DB_PASSWORD,
            hostname=self.hostname)
        self.hostname2 = 'hostname2'
        self.writer2 = journaler.PostgresWriter(
            self, user=DB_USER, host=DB_HOST,
            database=DB_NAME,
            password=DB_PASSWORD,
            hostname=self.hostname2)
        self.reader = journaler.PostgresReader(
            self, user=DB_USER, host=DB_HOST,
            database=DB_NAME,
            password=DB_PASSWORD)
        yield self.writer.initiate()
        yield self.writer2.initiate()
        yield self.reader.initiate()

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

        yield self.writer2.insert_entries([
            e(agent_id='cool_agent', args='some args'),
            e(agent_id='cool_agent'),
            l(level=2, category='spam', log_name='eggs',
              timestamp=self.past2, message='n1'),
            l(level=1, category='becon', timestamp=self.past1, message='n2'),
            l(level=1, message='n3'),
            l(level=2, message='n4')])

    @defer.inlineCallbacks
    def testGettingJournalerEntries(self):
        yield self._populate_data()

        # test getting histories
        histories = yield self.reader.get_histories()
        self.assertEqual(3, len(histories))
        self.assertEqual('other_agent', histories[0].agent_id)
        self.assertEqual('some id', histories[1].agent_id)
        self.assertEqual(1, histories[0].instance_id)
        self.assertEqual(1, histories[1].instance_id)
        self.assertEqual(self.hostname, histories[0].hostname)
        self.assertEqual(self.hostname, histories[1].hostname)
        self.assertEqual('cool_agent', histories[2].agent_id)
        self.assertEqual(1, histories[2].instance_id)
        self.assertEqual(self.hostname2, histories[2].hostname)

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
        self.assertEqual(6, len(entries))
        self.assertEqual('other_agent', entries[0]['agent_id'])
        self.assertEqual('other_agent', entries[1]['agent_id'])

        # deleting entries
        yield self.reader.delete_top_journal_entries(2)
        entries = yield self.reader.get_bare_journal_entries()
        self.assertEqual(4, len(entries))
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
        self.assertEqual(set([self.hostname, self.hostname2]), set(hosts))

        #test getting categories
        categories = yield self.reader.get_log_categories()
        self.assertEqual(set(['feat', 'test', 'spam', 'becon']),
                         set(categories))

        # now limited for host
        categories = yield self.reader.get_log_categories(
            hostname=self.hostname)
        self.assertEqual(set(['feat', 'test']), set(categories))
        categories = yield self.reader.get_log_categories(
            hostname=self.hostname2)
        self.assertEqual(set(['spam', 'becon', 'feat']), set(categories))

        #now with time conditions
        categories = yield self.reader.get_log_categories(
            start_date=self.now-10, hostname=self.hostname)
        self.assertEqual(set(['feat']), set(categories))
        categories = yield self.reader.get_log_categories(
            end_date=self.now-10, hostname=self.hostname)
        self.assertEqual(set(['test']), set(categories))

        #test getting log names
        names = yield self.reader.get_log_names('test', hostname=self.hostname)
        self.assertEqual(2, len(names))
        self.assertEqual(set([None, 'log_name']), set(names))

        names = yield self.reader.get_log_names('test',
                                                start_date=self.past1-10,
                                                hostname=self.hostname)
        self.assertEqual(1, len(names))
        self.assertEqual([None], names)
        names = yield self.reader.get_log_names('test',
                                                end_date=self.past1-10,
                                                hostname=self.hostname)
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
        self.assertEqual(8, len(entries))

        # with time condition
        entries = yield self.reader.get_log_entries(start_date=self.now-10)
        self.assertEqual(4, len(entries))
        self.assertEqual('m3', entries[0]['message'])
        self.assertEqual('m4', entries[1]['message'])
        self.assertEqual('n3', entries[2]['message'])
        self.assertEqual('n4', entries[3]['message'])

        entries = yield self.reader.get_log_entries(end_date=self.now-10)
        self.assertEqual(4, len(entries))
        self.assertEqual('m1', entries[0]['message'])
        self.assertEqual('n1', entries[1]['message'])
        self.assertEqual('m2', entries[2]['message'])
        self.assertEqual('n2', entries[3]['message'])

        # filter by hostname
        entries = yield self.reader.get_log_entries(
            filters=[dict(level=5, hostname=self.hostname)])
        self.assertEqual(4, len(entries))

        # filter by category and host
        entries = yield self.reader.get_log_entries(
            filters=[dict(category='test', level=5, hostname=self.hostname)])
        self.assertEqual(2, len(entries))
        self.assertEqual('m1', entries[0]['message'])
        self.assertEqual('m2', entries[1]['message'])

        # category and time conditions
        # filter by category
        entries = yield self.reader.get_log_entries(
            filters=[dict(category='test', level=5, hostname=self.hostname)],
            start_date=self.now-10)
        self.assertEqual(0, len(entries))

        entries = yield self.reader.get_log_entries(
            filters=[dict(category='test', level=5, hostname=self.hostname)],
            end_date=self.now-10)
        self.assertEqual(2, len(entries))

        # filter by name and category
        entries = yield self.reader.get_log_entries(
            filters=[dict(category='test', level=5, name='log_name',
                          hostname=self.hostname)])
        self.assertEqual(1, len(entries))
        self.assertEqual('m1', entries[0]['message'])

        # filter by level
        entries = yield self.reader.get_log_entries(
            filters=[dict(category='test', level=1)])
        self.assertEqual(1, len(entries))
        self.assertEqual('m2', entries[0]['message'])

        # deleting top entries
        yield self.reader.delete_top_log_entries(4)

        # only 4 entries left
        entries = yield self.reader.get_log_entries()
        self.assertEqual(4, len(entries))

        # now categories test, spam, becon should be gone
        categories = yield self.reader.get_log_categories()
        self.assertEqual(['feat'], categories)

    @defer.inlineCallbacks
    def tearDown(self):
        yield self.reader.close()
        yield self.writer.close()
        yield self.writer2.close()
        yield common.TestCase.tearDown(self)


class TestPostgressWriter(common.TestCase, ModelTestMixin, GenerateEntryMixin,
                          PostgresTestMixin):

    def setUp(self):
        common.TestCase.setUp(self)
        PostgresTestMixin.setUp(self)

    @defer.inlineCallbacks
    def testConnectingAndStoringEntry(self):
        writer = journaler.PostgresWriter(self, user=DB_USER, host=DB_HOST,
                                          database=DB_NAME,
                                          password=DB_PASSWORD)
        reader = journaler.PostgresReader(self, user=DB_USER, host=DB_HOST,
                                          database=DB_NAME,
                                          password=DB_PASSWORD)
        yield writer.initiate()
        yield reader.initiate()
        self.assertEqual(journaler.State.connected,
                         writer._get_machine_state())
        self.assertEqual(journaler.State.connected,
                         reader._get_machine_state())

        yield writer.insert_entries([self._generate_entry(),
                                     self._generate_log()])

        entries = yield reader.get_bare_journal_entries()
        self.assertEqual(1, len(entries))
        logs = yield reader.get_log_entries()
        self.assertEqual(1, len(logs))
        yield writer.close()
        yield reader.close()

        self.assertEqual(journaler.State.disconnected,
                         writer._get_machine_state())
        self.assertEqual(journaler.State.disconnected,
                         reader._get_machine_state())

        self.cursor.execute("SELECT COUNT(*) FROM feat.entries")
        self.assertEqual((1, ), self.cursor.fetchone())
        self.cursor.execute("SELECT COUNT(*) FROM feat.logs")
        self.assertEqual((1, ), self.cursor.fetchone())

    @defer.inlineCallbacks
    def testConnectingToNonexistantDb(self):
        writer = journaler.PostgresWriter(self, user='baduser', host=DB_HOST,
                                          database=DB_NAME,
                                          password=DB_PASSWORD,
                                          max_retries=1)
        d = writer.insert_entries([self._generate_entry(),
                                   self._generate_log()])
        self.assertFailure(d, defer.FirstError)

        yield writer.initiate()
        yield d
        # txpostgres hits reactor with errors, unfortunately, it takes
        # time for reactor to realize that
        yield common.delay(None, 0.1)
        self.addCleanup(self.flushLoggedErrors, psycopg2.OperationalError)

    @defer.inlineCallbacks
    def testMisconfiguredDb(self):
        self.cursor.execute('begin; drop schema feat cascade; commit')

        writer = journaler.PostgresWriter(self, user=DB_USER, host=DB_HOST,
                                          database=DB_NAME,
                                          password=DB_PASSWORD,
                                          max_retries=1)
        d = writer.insert_entries([self._generate_entry(),
                                   self._generate_log()])
        self.assertFailure(d, defer.FirstError)

        yield writer.initiate()
        yield d
        # txpostgres hits reactor with errors
        yield common.delay(None, 0.1)
        self.flushLoggedErrors(psycopg2.OperationalError)

    @defer.inlineCallbacks
    def testJournalerWith2ConnectionStrings(self):

        def connstr(user, password, host, name):
            return 'postgres://%s:%s@%s/%s' % (user, password, host, name)

        connstrs = [connstr(DB_USER, 'wrongpassword', DB_HOST, DB_NAME),
                    connstr(DB_USER, DB_PASSWORD, DB_HOST, DB_NAME)]
        jour = journaler.Journaler()
        jour.set_connection_strings(connstrs)
        jour.insert_entry(**self._generate_entry())

        def entries_stored():
            self.cursor.execute("SELECT COUNT(*) FROM feat.entries")
            return self.cursor.fetchone() == (1, )

        yield self.wait_for(entries_stored, 20)
        # txpostgres hits reactor with errors
        self.flushLoggedErrors(psycopg2.OperationalError)
        yield jour.close()

    @defer.inlineCallbacks
    def testFallbackToSqliteAndReconnect(self):

        def pg(user, password, host, name):
            return 'postgres://%s:%s@%s/%s' % (user, password, host, name)

        connstrs = [pg(DB_USER, DB_PASSWORD, DB_HOST, DB_NAME),
                    'sqlite://testFallbackToSqliteAndReconnect.sqlite3']
        jour = journaler.Journaler()
        yield jour.set_connection_strings(connstrs)
        yield jour.insert_entry(**self._generate_entry())

        # validate the view
        model = models.Journaler(jour)
        yield self.validate_model_tree(model)

        # connect to sqlite
        yield jour.use_next_writer()

        self.assertIsInstance(jour._writer, journaler.SqliteWriter)
        self.assertEqual(1, jour.current_target_index)

        jour.insert_entry(**self._generate_log(
            message='Very special log entry'))

        yield model.perform_action('reconnect')
        self.assertIsInstance(jour._writer, journaler.PostgresWriter)
        self.assertEqual(0, jour.current_target_index)

        self.cursor.execute("SELECT COUNT(*) FROM feat.logs WHERE "
                            "message='Very special log entry'")
        self.assertEqual((1, ), self.cursor.fetchone())
        yield jour.close()
