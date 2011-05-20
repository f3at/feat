import tempfile
import os

from feat.test import common
from feat.common import defer
from feat.agencies import journaler
from feat.common.serialization import banana


class Journaler(journaler.Journaler, common.Mock):

    def __init__(self, *args, **kwargs):
        common.Mock.__init__(self)
        journaler.Journaler.__init__(self, *args, **kwargs)

    _create_schema = common.Mock.record(journaler.Journaler._create_schema)


class DBTests(common.TestCase):

    timeout = 2

    def setUp(self):
        common.TestCase.setUp(self)
        self.serializer = banana.Serializer()
        self.unserializer = banana.Unserializer()

    @defer.inlineCallbacks
    def testInitiateInMemory(self):
        jour = journaler.Journaler(self)
        self.assertEqual(':memory:', jour._filename)
        self.assertFalse(jour.running)

        yield jour.initiate()
        self.assertTrue(jour.running)
        yield jour.close()
        self.assertFalse(jour.running)

    @defer.inlineCallbacks
    def testStoringAndReadingEntries(self):
        jour = journaler.Journaler(self, encoding='zip')
        yield jour.initiate()
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
        jour = Journaler(self, filename=filename)
        yield jour.initiate()
        self.assertCalled(jour, '_create_schema', times=1)
        self.assertTrue(jour.running)
        yield jour.close()
        self.assertFalse(jour.running)
        yield jour.initiate()
        self.assertTrue(jour.running)
        yield jour.close()
        self.assertCalled(jour, '_create_schema', times=1)

    @defer.inlineCallbacks
    def testLoadingCorrectEncoding(self):
        filename = self._get_tmp_file()
        jour = Journaler(self, filename=filename, encoding='zip')
        yield jour.initiate()
        yield jour.close()

        jour = Journaler(self, filename=filename, encoding='sth else')
        yield jour.initiate()
        # stored value should win
        self.assertEqual('zip', jour._encoding)

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
