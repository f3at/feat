import os
import optparse
import operator

from twisted.internet import defer
from twisted.spread import jelly, pb

from feat.test import common
from feat.process import couchdb, rabbitmq
from feat.agencies import agency as base_agency
from feat.agencies.net import agency, database
from feat.agents.base import agent, descriptor, dbtools, partners
from feat.common import first
from feat.process.base import DependencyError
from twisted.trial.unittest import SkipTest

from feat.interface.agent import *


jelly.globalSecurity.allowModules(__name__)


class OptParseMock(object):
    msg_port = '1999'
    manhole_public_key = 'file2'
    agent_name = 'name'


class UnitTestCase(common.TestCase):

    def setUp(self):
        common.TestCase.setUp(self)
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
        self.agency._store_config(env)
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


class StandalonePartners(partners.Partners):

    default_role = u'standalone'


@agent.register('standalone')
class StandaloneAgent(agent.BaseAgent):

    partners_class = StandalonePartners

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
    partners_class = StandalonePartners

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


@common.attr('slow')
class IntegrationTestCase(common.TestCase):

    configurable_attributes = ['run_rabbit', 'run_couch']
    run_rabbit = True
    run_couch = True

    @defer.inlineCallbacks
    def _run_and_configure_db(self):
        yield self.db_process.restart()
        c = self.db_process.get_config()
        db_host, db_port, db_name = c['host'], c['port'], 'test'
        db = database.Database(db_host, db_port, db_name)
        self.db = db.get_connection()
        yield dbtools.create_db(self.db)
        yield dbtools.push_initial_data(self.db)
        defer.returnValue((db_host, db_port, db_name, ))

    @defer.inlineCallbacks
    def _run_and_configure_msg(self):
        yield self.msg_process.restart()
        c = self.msg_process.get_config()
        msg_host, msg_port = '127.0.0.1', c['port']
        defer.returnValue((msg_host, msg_port, ))

    @defer.inlineCallbacks
    def setUp(self):
        common.TestCase.setUp(self)

        try:
            self.db_process = couchdb.Process(self)
        except DependencyError:
            raise SkipTest("No CouchDB server found.")

        try:
            self.msg_process = rabbitmq.Process(self)
        except DependencyError:
            raise SkipTest("No RabbitMQ server found.")


        if self.run_couch:
            db_host, db_port, db_name = yield self._run_and_configure_db()
        else:

            db_host, db_name = '127.0.0.1', 'test'
            db_port = self.db_process.get_free_port()

        if self.run_rabbit:
            msg_host, msg_port = yield self._run_and_configure_msg()
        else:
            msg_host, msg_port = '127.0.0.1', self.msg_process.get_free_port()

        jourfile = "%s.sqlite3" % (self._testMethodName, )

        self.agency = agency.Agency(
            msg_host=msg_host, msg_port=msg_port,
            db_host=db_host, db_port=db_port, db_name=db_name,
            agency_journal=jourfile)
        yield self.agency.initiate()

    @defer.inlineCallbacks
    def testStartStandaloneAgent(self):
        yield self.wait_for_host_agent(10)
        host_a = self.agency._get_host_agent()

        yield self.agency.spawn_agent("standalone")

        yield self.wait_for_standalone()
        part = host_a.query_partners_with_role('all', 'standalone')

        agent_ids = [host_a.get_own_address().key, part[0].recipient.key]
        # check that journaling works as it should
        yield self.assert_journal_contains(agent_ids)

        # now test the find_agent logic
        host = yield self.agency.find_agent(agent_ids[0])
        self.assertIsInstance(host, base_agency.AgencyAgent)
        stand = yield self.agency.find_agent(agent_ids[1])
        self.assertIsInstance(stand, pb.RemoteReference)

        slave = first(self.agency._broker.iter_slaves())
        self.assertIsInstance(slave, pb.RemoteReference)
        host = yield slave.callRemote('find_agent', agent_ids[0])
        self.assertIsInstance(host, base_agency.AgencyAgent)
        stand = yield slave.callRemote('find_agent', agent_ids[1])
        self.assertIsInstance(stand, pb.RemoteReference)

        not_found = yield slave.callRemote('find_agent', 'unknown id')
        self.assertIs(None, not_found)

    @defer.inlineCallbacks
    def testStartStandaloneArguments(self):
        yield self.wait_for_host_agent(10)
        host_a = self.agency._get_host_agent()

        # this will be called in the other process
        yield self.agency.spawn_agent('standalone_with_args',
                                      None, 1, 2, 3, foo=4, bar=5)

        yield self.wait_for_standalone()
        part = host_a.query_partners_with_role('all', 'standalone')
        self.assertEqual(1, len(part))

        yield self.assert_journal_contains(
            [host_a.get_own_address().key, part[0].recipient.key])

    @common.attr(run_rabbit=False, run_couch=False)
    @defer.inlineCallbacks
    def testStartupWithoutConnections(self):
        '''
        This testcase runs the agency with missconfigured connections.
        It reconfigures it, and asserts that host agent has been started
        normally. Than it simulates host agent being burried (by deleting
        the descriptor) and asserts that the new host agent has been started.
        '''
        self.assertEqual(None, self.agency._get_host_medium())
        self.info("Starting rabbit")
        msg_host, msg_port = yield self._run_and_configure_msg()
        self.info("Starting couch")
        db_host, db_port, db_name = yield self._run_and_configure_db()
        self.info("Reconfiguring the agency")
        self.agency.reconfigure_messaging(msg_host, msg_port)
        self.agency.reconfigure_database(db_host, db_port, db_name)

        yield self.wait_for_host_agent(10)
        medium = self.agency._get_host_medium()
        yield medium.wait_for_state(AgencyAgentState.ready)

        yield self.wait_for(self.agency.is_idle, 20)

        # now delete the host agents descriptor to look what happens
        agent_id = medium.get_descriptor().doc_id
        desc = yield self.db.get_document(agent_id)
        yield self.db.delete_document(desc)

        yield medium.wait_for_state(AgencyAgentState.terminated)

        yield self.wait_for_host_agent(10)
        new_medium = self.agency._get_host_medium()
        yield new_medium.wait_for_state(AgencyAgentState.ready)
        new_agent_id = new_medium.get_descriptor().doc_id

        self.assertNotEqual(new_agent_id, agent_id)

    @defer.inlineCallbacks
    def tearDown(self):
        yield self.wait_for(self.agency.is_idle, 20)
        yield self.agency.full_shutdown()
        yield self.db_process.terminate()
        yield self.msg_process.terminate()

    @defer.inlineCallbacks
    def assert_journal_contains(self, agent_ids):
        jour = self.agency._journaler
        resp = yield jour.get_histories()
        ids_got = map(operator.attrgetter('agent_id'), resp)
        set1 = set(agent_ids)
        set2 = set(ids_got)
        self.assertTrue(set1.issubset(set2),
                        "%r is not subset of %r" % (set1, set2, ))

    def wait_for_host_agent(self, timeout):

        def check():
            medium = self.agency._get_host_medium()
            return medium is not None

        return self.wait_for(check, timeout)

    def wait_for_standalone(self, timeout=20):

        host_a = self.agency._get_host_agent()
        self.assertIsNot(host_a, None)

        def has_partner():
            part = host_a.query_partners_with_role('all', 'standalone')
            return len(part) == 1

        return self.wait_for(has_partner, timeout)
