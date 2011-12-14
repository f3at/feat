from feat.common import connstr
from feat.test import common


class ConnStrTest(common.TestCase):

    def testParsingConnstr(self):
        resp = connstr.parse('ftp://fff.sss.ggg')
        self.assertEqual('ftp', resp['protocol'])
        self.assertEqual(None, resp['user'])
        self.assertEqual(None, resp['password'])
        self.assertEqual(None, resp['port'])
        self.assertEqual('fff.sss.ggg', resp['host'])

        resp = connstr.parse('postgres://feat:feat@encoder001.fff.sss.ggg')
        self.assertEqual('postgres', resp['protocol'])
        self.assertEqual('feat', resp['user'])
        self.assertEqual('feat', resp['password'])
        self.assertEqual(None, resp['port'])
        self.assertEqual('encoder001.fff.sss.ggg', resp['host'])

        resp = connstr.parse('sqlite:///var/log/journal.sqlite3')
        self.assertEqual('sqlite', resp['protocol'])
        self.assertEqual(None, resp['user'])
        self.assertEqual(None, resp['password'])
        self.assertEqual(None, resp['port'])
        self.assertEqual('/var/log/journal.sqlite3', resp['host'])
