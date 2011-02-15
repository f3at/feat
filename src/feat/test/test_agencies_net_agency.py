import os

from twisted.internet import defer

from feat.test import common
from feat.process import couchdb, rabbitmq
from feat.agencies.net import agency, database
from feat.agents.host import host_agent
from feat.agents.base import agent, descriptor
from feat.common import serialization


class UnitTestCase(common.TestCase):

    def setUp(self):
        self.agency = agency.Agency.__new__(agency.Agency)

    def testLoadConfig(self):
        env = {
            'FEAT_AGENT_ID': 'agent_id',
            'FEAT_MSG_PORT': '2000',
            'FEAT_MANHOLE_PUBLIC_KEY': 'file'}
        self.agency._load_config(env)
        self.assertTrue('agent' in self.agency.config)
        self.assertEqual('agent_id', self.agency.config['agent']['id'])
        self.assertTrue('msg' in self.agency.config)
        self.assertEqual('2000', self.agency.config['msg']['port'])
        self.assertTrue('manhole' in self.agency.config)
        self.assertEqual('file', self.agency.config['manhole']['public_key'])

    def testStoreConfig(self):
        self.agency.config = dict()
        self.agency.config['msg'] = dict(port=3000, host='localhost')
        self.agency.config['manhole'] = dict(public_key='file')
        env = dict()
        env = self.agency._store_config(env)
        self.assertEqual('localhost', env['FEAT_MSG_HOST'])
        self.assertEqual('3000', env['FEAT_MSG_PORT'])
        self.assertEqual('file', env['FEAT_MANHOLE_PUBLIC_KEY'])


@agent.register('standalone')
class StandaloneAgent(agent.BaseAgent):

    standalone = True

    @staticmethod
    def get_cmd_line():
        src_path = os.path.abspath(os.path.join(
            os.path.dirname(__file__), '..', '..'))
        command = os.path.join(src_path, 'feat', 'bin', 'standalone.py')
        logfile = os.path.join(src_path, 'standalone.log')
        args = ['-i', 'feat.test.test_agencies_net_agency',
                '-l', logfile]
        env = dict(PYTHONPATH=src_path, FEAT_DEBUG='5')
        return command, args, env


@serialization.register
class Descriptor(descriptor.Descriptor):

    document_type = 'standalone'


@common.attr('slow')
class IntegrationTestCase(common.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        self.db_process = couchdb.Process(common.DummyRecordNode(self))
        yield self.db_process.restart()
        c = self.db_process.get_config()
        db_host, db_port, db_name = c['host'], c['port'], 'test'
        db = database.Database(db_host, db_port, db_name)
        self.db = db.get_connection(None)
        yield db.createDB()

        self.msg_process = rabbitmq.Process(common.DummyRecordNode(self))
        yield self.msg_process.restart()
        c = self.msg_process.get_config()
        msg_host, msg_port = '127.0.0.1', c['port']
        self.agency = agency.Agency(
            msg_host=msg_host, msg_port=msg_port,
            db_host=db_host, db_port=db_port, db_name=db_name)

    @defer.inlineCallbacks
    def testStartStandaloneAgent(self):
        desc = host_agent.Descriptor(shard=u'lobby')
        desc = yield self.db.save_document(desc)
        yield self.agency.start_agent(desc, bootstrap=True)
        self.assertEqual(1, len(self.agency._agents))
        host_a = self.agency._agents[0].get_agent()

        # this will be called in the other process
        desc = Descriptor()
        desc = yield self.db.save_document(desc)
        yield host_a.start_agent(desc.doc_id)

        part = host_a.query_partners('all')
        self.assertEqual(1, len(part))

    @defer.inlineCallbacks
    def tearDown(self):
        yield self.agency.shutdown()
        yield self.db_process.terminate()
        yield self.msg_process.terminate()
