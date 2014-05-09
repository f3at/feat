import mock

from feat.test import common
from feat.database import driver


class InitializingFromCanonicalUrl(common.TestCase):

    def setUp(self):
        self.cls = cls = driver.Database
        cls.reconnect = mock.Mock()

        self.instance = cls.from_canonical_url

    def tearDown(self):
        self.assertTrue(self.cls.reconnect.called)

    def testSimpleName(self):
        d = self.instance('feat')
        self.assertEqual('localhost', d.host)
        self.assertEqual(5985, d.port)
        self.assertEqual('feat', d.db_name)
        self.assertEqual(None, d.username)
        self.assertEqual(None, d.password)
        self.assertEqual(False, d.https)

    def testUrl(self):
        d = self.instance('http://some.host:5983/feat')
        self.assertEqual('some.host', d.host)
        self.assertEqual(5983, d.port)
        self.assertEqual('feat', d.db_name)
        self.assertEqual(None, d.username)
        self.assertEqual(None, d.password)
        self.assertEqual(False, d.https)

    def testUrlWithCredentials(self):
        d = self.instance('https://user:password@some.host:5983/feat')
        self.assertEqual('some.host', d.host)
        self.assertEqual(5983, d.port)
        self.assertEqual('feat', d.db_name)
        self.assertEqual('user', d.username)
        self.assertEqual('password', d.password)
        self.assertEqual(True, d.https)

