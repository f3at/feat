import signal
import tempfile
import os

from feat.test import common
from feat.common import defer
from feat.agencies import journaler
from feat.common.serialization import banana


class SqliteWriter(journaler.SqliteWriter, common.Mock):

    def __init__(self, *args, **kwargs):
        common.Mock.__init__(self)
        journaler.SqliteWriter.__init__(self, *args, **kwargs)

    _create_schema = common.Mock.record(journaler.SqliteWriter._create_schema)


class DBTests(common.TestCase):

    timeout = 2

    def setUp(self):
        common.TestCase.setUp(self)
        self.serializer = banana.Serializer()
        self.unserializer = banana.Unserializer()

    @defer.inlineCallbacks
    def testInitiateInMemory(self):
        jour = journaler.Journaler(self)
        writer = journaler.SqliteWriter(self)
        jour.configure_with(writer)

        self.assertEqual(journaler.State.connected,
                         jour._get_machine_state())

        filename = yield jour.get_filename()
        self.assertEqual(':memory:', filename)
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
        jour = journaler.Journaler(self)
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
        jour = journaler.Journaler(self)
        writer = journaler.SqliteWriter(self, encoding='zip')
        yield writer.initiate()
        yield jour.configure_with(writer)

        yield jour.insert_entry(**self._generate_data())
        histories = yield jour.get_histories()
        self.assertIsInstance(histories, list)
        self.assertIsInstance(histories[0], journaler.History)

        entries = yield jour.get_entries(histories[0])
        self.assertIsInstance(entries, list)
        self.assertEqual(1, len(entries))
        unpacked = self._unpack(entries[0])
        self.assertEqual('some id', unpacked['a_id'])
        self.assertEqual('some.canonical.name', unpacked['fun_id'])
        self.assertEqual(('some_id', 1, 0, ),
                         self.unserializer.convert(unpacked['j_id']))
        self.assertEqual(None,
                         self.unserializer.convert(unpacked['res']))
        self.assertEqual(list(),
                         self.unserializer.convert(unpacked['sfx']))

        yield jour.insert_entry(**self._generate_data(function_id='other'))
        entries = yield jour.get_entries(histories[0])
        self.assertEqual(2, len(entries))
        first = self._unpack(entries[0])
        second = self._unpack(entries[1])
        self.assertEqual('some.canonical.name', first['fun_id'])
        self.assertEqual('other', second['fun_id'])

    def _unpack(self, row):
        keys = ('a_id', 'i_id', 'j_id', 'fun_id', 'f_id',
                'f_dep', 'args', 'kwargs', 'sfx', 'res', 'time', )
        return dict(zip(keys, row))

    @defer.inlineCallbacks
    def testInitiateOnDisk(self):
        filename = self._get_tmp_file()
        jour = journaler.Journaler(self)
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
        filename = self._get_tmp_file()
        jour = journaler.Journaler(self)
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

    def _get_tmp_file(self):
        fd, name = tempfile.mkstemp(suffix='_journal.sqlite')
        self.addCleanup(os.remove, name)
        return name

    def _generate_data(self, **opts):
        defaults = {
            'agent_id': 'some id',
            'instance_id': 1,
            'journal_id': self.serializer.convert(('some_id', 1, 0, )),
            'function_id': 'some.canonical.name',
            'args': self.serializer.convert(tuple()),
            'kwargs': self.serializer.convert(dict()),
            'fiber_id': 'some fiber id',
            'fiber_depth': 1,
            'result': self.serializer.convert(None),
            'side_effects': self.serializer.convert(list())}

        defaults.update(opts)
        return defaults

    @defer.inlineCallbacks
    def _assert_entries(self, jour, num):
        histories = yield jour.get_histories()
        self.assertIsInstance(histories, list)
        if num > 0:
            self.assertIsInstance(histories[0], journaler.History)
            entries = yield jour.get_entries(histories[0])
            self.assertIsInstance(entries, list)
            self.assertEqual(num, len(entries))
