from feat.test import common
from feat.agencies.net import agency


class NetAgencyTest(common.TestCase):

    def setUp(self):
        self.agency = agency.Agency.__new__(agency.Agency)

    def testLoadConfig(self):
        env = {
            'FEAT_AGENT_ID': 'agent_id',
            'FEAT_MSG_PORT': 2000,
            'FEAT_MANHOLE_PUBLIC_KEY': 'file'}
        self.agency._load_config(env)
        self.assertTrue('agent' in self.agency.config)
        self.assertEqual('agent_id', self.agency.config['agent']['id'])
        self.assertTrue('msg' in self.agency.config)
        self.assertEqual(2000, self.agency.config['msg']['port'])
        self.assertTrue('manhole' in self.agency.config)
        self.assertEqual('file', self.agency.config['manhole']['public_key'])

    def testStoreConfig(self):
        self.agency.config = dict()
        self.agency.config['msg'] = dict(port=3000, host='localhost')
        self.agency.config['manhole'] = dict(public_key='file')
        env = dict()
        env = self.agency._store_config(env)
        self.assertEqual('localhost', env['FEAT_MSG_HOST'])
        self.assertEqual(3000, env['FEAT_MSG_PORT'])
        self.assertEqual('file', env['FEAT_MANHOLE_PUBLIC_KEY'])
