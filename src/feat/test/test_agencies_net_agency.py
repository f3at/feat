import os
import optparse

from twisted.internet import defer
from twisted.spread import jelly

from feat.test import common
from feat.process import couchdb, rabbitmq
from feat.agencies.net import agency, database
from feat.agents.host import host_agent
from feat.agents.base import agent, descriptor, replay
from feat.common import serialization, fiber
from feat.process.base import DependencyError
from twisted.trial.unittest import SkipTest


jelly.globalSecurity.allowModules(__name__)


class OptParseMock(object):
    msg_port = '1999'
    manhole_public_key = 'file2'
    agent_name = 'name'


class UnitTestCase(common.TestCase):

    def setUp(self):
        self.agency = agency.Agency()

    def testLoadConfig(self):
        env = {
            'FEAT_AGENT_ID': 'agent_id',
            'FEAT_AGENT_ARGS': 'agent_args',
            'FEAT_AGENT_KWARGS': 'agent_kwargs',
            'FEAT_MSG_PORT': '2000',
            'FEAT_MANHOLE_PUBLIC_KEY': 'file'}
        self.agency._init_config()
        # Test extra configuration values
        self.agency.config["agent"] = {"id": None,
                                       "args": None,
                                       "kwargs": None}
        self.agency._load_config(env)
        self.assertTrue('agent' in self.agency.config)
        self.assertEqual('agent_id', self.agency.config['agent']['id'])
        self.assertEqual('agent_args', self.agency.config['agent']['args'])
        self.assertEqual('agent_kwargs', self.agency.config['agent']['kwargs'])
        self.assertTrue('msg' in self.agency.config)
        self.assertEqual('2000', self.agency.config['msg']['port'])
        self.assertTrue('manhole' in self.agency.config)
        self.assertEqual('file', self.agency.config['manhole']['public_key'])
        self.assertFalse('name' in self.agency.config['agent'])

        #Overwrite some configuration values
        self.agency._load_config(env, OptParseMock())
        self.assertEqual('1999', self.agency.config['msg']['port'])
        self.assertEqual('file2', self.agency.config['manhole']['public_key'])
        self.assertFalse('name' in self.agency.config['agent'])

    def testStoreConfig(self):
        self.agency.config = dict()
        self.agency.config['msg'] = dict(port=3000, host='localhost')
        self.agency.config['manhole'] = dict(public_key='file')
        env = dict()
        env = self.agency._store_config(env)
        self.assertEqual('localhost', env['FEAT_MSG_HOST'])
        self.assertEqual('3000', env['FEAT_MSG_PORT'])
        self.assertEqual('file', env['FEAT_MANHOLE_PUBLIC_KEY'])

    def testDefaultConfig(self):
        parser = optparse.OptionParser()
        agency.add_options(parser)
        options = parser.get_default_values()
        self.assertTrue(hasattr(options, 'msg_host'))
        self.assertTrue(hasattr(options, 'msg_port'))
        self.assertTrue(hasattr(options, 'msg_user'))
        self.assertTrue(hasattr(options, 'msg_password'))
        self.assertTrue(hasattr(options, 'db_host'))
        self.assertTrue(hasattr(options, 'db_port'))
        self.assertTrue(hasattr(options, 'db_name'))
        self.assertTrue(hasattr(options, 'manhole_public_key'))
        self.assertTrue(hasattr(options, 'manhole_private_key'))
        self.assertTrue(hasattr(options, 'manhole_authorized_keys'))
        self.assertTrue(hasattr(options, 'manhole_port'))
        self.assertEqual(options.msg_host, agency.DEFAULT_MSG_HOST)
        self.assertEqual(options.msg_port, agency.DEFAULT_MSG_PORT)
        self.assertEqual(options.msg_user, agency.DEFAULT_MSG_USER)
        self.assertEqual(options.msg_password, agency.DEFAULT_MSG_PASSWORD)
        self.assertEqual(options.db_host, agency.DEFAULT_DB_HOST)
        self.assertEqual(options.db_port, agency.DEFAULT_DB_PORT)
        self.assertEqual(options.db_name, agency.DEFAULT_DB_NAME)
        self.assertEqual(options.manhole_public_key, agency.DEFAULT_MH_PUBKEY)
        self.assertEqual(options.manhole_private_key,
                         agency.DEFAULT_MH_PRIVKEY)
        self.assertEqual(options.manhole_authorized_keys,
                         agency.DEFAULT_MH_AUTH)
        self.assertEqual(options.manhole_port, agency.DEFAULT_MH_PORT)


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


@descriptor.register('standalone')
class Descriptor(descriptor.Descriptor):
    pass


@agent.register('standalone_with_args')
class StandaloneAgentWithArgs(agent.BaseAgent):

    standalone = True

    @staticmethod
    def get_cmd_line(*args, **kwargs):
        if args != (1, 2, 3) or kwargs != {"foo": 4, "bar": 5}:
            raise Exception("Unexpected arguments or keyword in get_cmd_line()"
                            ": %r %r" % (args, kwargs))
        src_path = os.path.abspath(os.path.join(
            os.path.dirname(__file__), '..', '..'))
        command = os.path.join(src_path, 'feat', 'bin', 'standalone.py')
        logfile = os.path.join(src_path, 'standalone.log')
        args = ['-i', 'feat.test.test_agencies_net_agency',
                '-l', logfile]
        env = dict(PYTHONPATH=src_path, FEAT_DEBUG='5')
        return command, args, env

    def initiate(self, *args, **kwargs):
        if args != (1, 2, 3) or kwargs != {"foo": 4, "bar": 5}:
            raise Exception("Unexpected arguments or keyword in initiate()"
                            ": %r %r" % (args, kwargs))
        agent.BaseAgent.initiate(self)


@descriptor.register('standalone_with_args')
class DescriptorWithArgs(descriptor.Descriptor):
    pass


@agent.register('standalone-master')
class MasterAgent(StandaloneAgent):
    """
    This agents job is to start another standalone agent from his standalone
    agency to check that we recreate 3 processes (1 master + 2 standalones).
    """

    @staticmethod
    def get_cmd_line():
        command, args, env = StandaloneAgent.get_cmd_line()
        src_path = os.path.abspath(os.path.join(
            os.path.dirname(__file__), '..', '..'))
        logfile = os.path.join(src_path, 'master.log')
        args = ['-i', 'feat.test.test_agencies_net_agency',
                '-l', logfile]
        return command, args, env

    @replay.entry_point
    def initiate(self, state):
        StandaloneAgent.initiate(self)

        desc = Descriptor(shard='lobby')
        f = fiber.Fiber()
        f.add_callback(state.medium.save_document)
        f.add_callback(state.medium.start_agent)
        f.add_callback(self.establish_partnership)
        return f.succeed(desc)


@serialization.register
class MasterDescriptor(descriptor.Descriptor):

    document_type = 'standalone-master'


@common.attr('slow')
class IntegrationTestCase(common.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        try:
            self.db_process = couchdb.Process(self)
        except DependencyError:
            raise SkipTest("No CouchDB server found.")

        try:
            self.msg_process = rabbitmq.Process(self)
        except DependencyError:
            raise SkipTest("No RabbitMQ server found.")


        yield self.db_process.restart()
        c = self.db_process.get_config()
        db_host, db_port, db_name = c['host'], c['port'], 'test'
        db = database.Database(db_host, db_port, db_name)
        self.db = db.get_connection(None)
        yield db.createDB()

        yield self.msg_process.restart()
        c = self.msg_process.get_config()
        msg_host, msg_port = '127.0.0.1', c['port']
        self.agency = agency.Agency(
            msg_host=msg_host, msg_port=msg_port,
            db_host=db_host, db_port=db_port, db_name=db_name)
        yield self.agency.initiate()

    def check_journal_entries(self):
        self.assertEqual(len(self.agency._journal_entries), 0)

    @defer.inlineCallbacks
    def testStartStandaloneAgent(self):
        desc = host_agent.Descriptor(shard=u'lobby')
        desc = yield self.db.save_document(desc)
        yield self.agency.start_agent(desc, run_startup=False)
        self.assertEqual(1, len(self.agency._agents))
        host_a = self.agency._agents[0].get_agent()

        # this will be called in the other process
        desc = Descriptor()
        desc = yield self.db.save_document(desc)
        yield host_a.start_agent(desc.doc_id)

        part = host_a.query_partners('all')
        self.assertEqual(1, len(part))
        self.check_journal_entries()

    @defer.inlineCallbacks
    def testStartStandaloneArguments(self):
        desc = host_agent.Descriptor(shard=u'lobby')
        desc = yield self.db.save_document(desc)
        yield self.agency.start_agent(desc, run_startup=False)
        self.assertEqual(1, len(self.agency._agents))
        host_a = self.agency._agents[0].get_agent()

        # this will be called in the other process
        desc = DescriptorWithArgs()
        desc = yield self.db.save_document(desc)
        yield host_a.start_agent(desc.doc_id, None, 1, 2, 3, foo=4, bar=5)

        part = host_a.query_partners('all')
        self.assertEqual(1, len(part))
        self.check_journal_entries()

    @defer.inlineCallbacks
    def testStartAgentFromStandalone(self):
        desc = host_agent.Descriptor(shard=u'lobby')
        desc = yield self.db.save_document(desc)
        yield self.agency.start_agent(desc)
        self.assertEqual(1, len(self.agency._agents))
        host_a = self.agency._agents[0].get_agent()

        # this will be called in the other process
        desc = MasterDescriptor()
        desc = yield self.db.save_document(desc)
        yield host_a.start_agent(desc.doc_id)

        part = host_a.query_partners('all')
        self.assertEqual(1, len(part))

        self.assertEqual(2, len(self.agency._broker.slaves))
        for slave in self.agency._broker.slaves:
            mediums = yield slave.callRemote('get_agents')
            self.assertEqual(1, len(mediums))
        self.check_journal_entries()

    @defer.inlineCallbacks
    def tearDown(self):
        yield self.agency.full_shutdown()
        yield self.db_process.terminate()
        yield self.msg_process.terminate()
