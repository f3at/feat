import os

from twisted.trial.unittest import SkipTest

from feat.agencies import journaler
from feat.common import defer, time
from feat.common.serialization import banana
from feat.gateway import models
from feat.test import common
from feat.test.integration.common import ModelTestMixin

psycopg2 = None
try:
    import psycopg2
    import psycopg2.extensions
except ImportError:
    pass


DB_NAME = "feat_test"
DB_HOST = "localhost"
DB_USER = "feat_test"
DB_PASSWORD = "feat_test"


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


class TestPostgressWriter(common.TestCase, ModelTestMixin):

    skip = _skip

    def setUp(self):
        common.TestCase.setUp(self)
        self.serializer = banana.Serializer()
        self.unserializer = banana.Unserializer()

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

    @defer.inlineCallbacks
    def testConnectingAndStoringEntry(self):
        writer = journaler.PostgresWriter(self, user=DB_USER, host=DB_HOST,
                                          database=DB_NAME,
                                          password=DB_PASSWORD)
        yield writer.initiate()
        self.assertEqual(journaler.State.connected,
                         writer._get_machine_state())

        yield writer.insert_entries([self._generate_entry(),
                                     self._generate_log()])

        yield writer.close()
        self.assertEqual(journaler.State.disconnected,
                         writer._get_machine_state())

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
                    'sqlite://journal.sqlite3']
        jour = journaler.Journaler()
        jour.set_connection_strings(connstrs)
        jour.insert_entry(**self._generate_entry())

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

        # txpostgres will leave the error in the reactor,
        # it's just a way it is, sorry
        from twisted.internet.error import ConnectionDone
        self.flushLoggedErrors(ConnectionDone)

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

    def _generate_entry(self, **opts):
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
