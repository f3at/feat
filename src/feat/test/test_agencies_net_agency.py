# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.
import socket
import sys
import os
import optparse
import operator

from twisted.internet import defer
from twisted.spread import pb

from feat.test import common
from feat.process import couchdb, rabbitmq, standalone
from feat.agencies import agency as base_agency
from feat.agencies.net import agency, database, broker
from feat.agencies.net import options as options_module
from feat.agents.base import agent, descriptor, dbtools, partners, replay
from feat.common import serialization, fiber, log, first
from feat.process.base import DependencyError
from twisted.trial.unittest import SkipTest

from feat.interface.agent import AgencyAgentState


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
        options_module.add_options(parser)
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
        a = agency.Agency.from_config(dict())
        self.assertEqual(a.config['msg']['host'],
                         options_module.DEFAULT_MSG_HOST)
        self.assertEqual(a.config['msg']['port'],
                         options_module.DEFAULT_MSG_PORT)
        self.assertEqual(a.config['msg']['user'],
                         options_module.DEFAULT_MSG_USER)
        self.assertEqual(a.config['msg']['password'],
                         options_module.DEFAULT_MSG_PASSWORD)
        self.assertEqual(a.config['db']['host'],
                         options_module.DEFAULT_DB_HOST)
        self.assertEqual(a.config['db']['port'],
                         options_module.DEFAULT_DB_PORT)
        self.assertEqual(a.config['db']['name'],
                         options_module.DEFAULT_DB_NAME)
        self.assertEqual(a.config['manhole']['public_key'],
                         options_module.DEFAULT_MH_PUBKEY)
        self.assertEqual(a.config['manhole']['private_key'],
                         options_module.DEFAULT_MH_PRIVKEY)
        self.assertEqual(a.config['manhole']['authorized_keys'],
                         options_module.DEFAULT_MH_AUTH)
        self.assertEqual(a.config['manhole']['port'],
                         options_module.DEFAULT_MH_PORT)


class StandalonePartners(partners.Partners):

    default_role = u'standalone'


@agent.register('standalone')
class StandaloneAgent(agent.BaseAgent):

    partners_class = StandalonePartners

    standalone = True

    @staticmethod
    def get_cmd_line(desc, **kwargs):
        src_path = os.path.abspath(os.path.join(
            os.path.dirname(__file__), '..', '..'))
        bin_path = os.path.abspath(os.path.join(
            src_path, '..', 'bin'))

        agent_id = str(desc.doc_id)
        s_kwargs = serialization.json.serialize(kwargs)

        command = 'feat'
        args = ['-i', 'feat.test.test_agencies_net_agency',
                '-L', os.path.curdir,
                '-R', os.path.curdir,
                '-D',
                '-X',
                '-a', agent_id]
        if s_kwargs:
            args += ['--kwargs', s_kwargs]
        env = dict(PYTHONPATH=src_path, FEAT_DEBUG='5', PATH=bin_path)
        return command, args, env


@descriptor.register('standalone')
class Descriptor(descriptor.Descriptor):
    pass


@agent.register('standalone_with_args')
class StandaloneAgentWithArgs(StandaloneAgent):

    standalone = True
    partners_class = StandalonePartners

    @staticmethod
    def get_cmd_line(descriptor, **kwargs):
        if kwargs != {"foo": 4, "bar": 5}:
            raise Exception("Unexpected arguments or keyword in get_cmd_line()"
                            ": %r" % (kwargs, ))
        return StandaloneAgent.get_cmd_line(descriptor, **kwargs)

    def initiate(self, foo, bar):
        if foo != 4 or bar != 5:
            raise Exception("Unexpected arguments or keyword in initiate()")


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

        desc = Descriptor(shard=u'lobby')
        f = fiber.Fiber()
        f.add_callback(fiber.bridge_param, self.initiate_partners)
        f.add_callback(state.medium.save_document)
        f.add_callback(state.medium.start_agent)
        f.add_callback(self.establish_partnership)
        return f.succeed(desc)


@serialization.register
class MasterDescriptor(descriptor.Descriptor):

    document_type = 'standalone-master'


@common.attr('slow', timeout=40)
class IntegrationTestCase(common.TestCase):

    configurable_attributes = ['run_rabbit', 'run_couch', 'shutdown']
    run_rabbit = True
    run_couch = True
    shutdown = True

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
        self.tempdir = os.path.curdir
        self.socket_path = os.path.join(os.path.curdir, 'feat-test.socket')

        bin_dir = os.path.abspath(os.path.join(
            os.path.curdir, '..', '..', 'bin'))
        os.environ["PATH"] = ":".join([bin_dir, os.environ["PATH"]])

        try:
            self.db_process = couchdb.Process(self)
        except DependencyError:
            raise SkipTest("No CouchDB server found.")

        try:
            self.msg_process = rabbitmq.Process(self)
        except DependencyError:
            raise SkipTest("No RabbitMQ server found.")


        if self.run_couch:
            self.db_host, self.db_port, self.db_name =\
                          yield self._run_and_configure_db()
        else:

            self.db_host, self.db_name = '127.0.0.1', 'test'
            self.db_port = self.db_process.get_free_port()

        if self.run_rabbit:
            self.msg_host, self.msg_port = yield self._run_and_configure_msg()
        else:
            self.msg_host = '127.0.0.1'
            self.msg_port = self.msg_process.get_free_port()

        self.jourfile = "%s.sqlite3" % (self._testMethodName, )

        self.agency = agency.Agency(
            msg_host=self.msg_host, msg_port=self.msg_port,
            db_host=self.db_host, db_port=self.db_port, db_name=self.db_name,
            agency_journal=self.jourfile, rundir=self.tempdir,
            logdir=self.tempdir,
            socket_path=self.socket_path)

    @defer.inlineCallbacks
    def testStartStandaloneAgent(self):
        yield self.agency.initiate()
        yield self.wait_for_host_agent(20)
        host_a = self.agency._get_host_agent()
        yield host_a.wait_for_ready()

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

        slave = first(x for x in self.agency._broker.slaves.itervalues()
                      if x.is_standalone)

        self.assertIsInstance(slave, broker.SlaveReference)
        host = yield slave.callRemote('find_agent', agent_ids[0])
        self.assertIsInstance(host, base_agency.AgencyAgent)
        stand = yield slave.callRemote('find_agent', agent_ids[1])
        self.assertIsInstance(stand, pb.RemoteReference)

        not_found = yield slave.callRemote('find_agent', 'unknown id')
        self.assertIs(None, not_found)

        # asserts on slaves registry
        self.assertEqual(2, len(self.agency._broker.slaves))
        self.assertEqual(1, len(slave.agents))
        self.assertEqual(agent_ids[1], slave.agents.keys()[0])
        self.assertEqual(stand, slave.agents.values()[0])

        # asserts on logs and journal entries in journal database
        jour = self.agency._journaler._writer
        yield self.wait_for(jour.is_idle, 10)
        categories = yield jour.get_log_categories()
        self.assertTrue(set(['host_agent', 'standalone', 'agency']).issubset(
            set(categories)))
        log_names = yield jour.get_log_names('host_agent')
        self.assertEqual([agent_ids[0]], log_names)
        log_names = yield jour.get_log_names('standalone')
        self.assertEqual([agent_ids[1]], log_names)
        yield self.assert_has_logs('host_agent', agent_ids[0])
        yield self.assert_has_logs('standalone', agent_ids[1])

    @defer.inlineCallbacks
    def testStartStandaloneArguments(self):
        yield self.agency.initiate()
        yield self.wait_for_host_agent(10)
        host_a = self.agency._get_host_agent()

        # this will be called in the other process
        yield self.agency.spawn_agent('standalone_with_args', foo=4, bar=5)

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
        yield self.agency.initiate()
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

    @defer.inlineCallbacks
    def testBackupAgency(self):
        pid_path = os.path.join(os.path.curdir, 'feat.pid')
        hostname = unicode(socket.gethostbyaddr(socket.gethostname())[0])

        process = yield self.spawn_agency()
        yield self.wait_for_pid(pid_path)

        @defer.inlineCallbacks
        def host_descriptor():
            host_desc = yield self.db.get_document(hostname)
            defer.returnValue(host_desc.instance_id == 1)

        yield self.wait_for(host_descriptor, 5)

        yield self.agency.initiate()
        yield self.wait_for_slave()
        yield process.terminate()
        yield self.wait_for_master()

        def has_host():
            m = self.agency._get_host_medium()
            return m is not None and m.is_ready()

        yield self.wait_for(has_host, 10)
        host_desc = yield self.db.get_document(hostname)
        self.assertEqual(2, host_desc.instance_id)

        yield self.wait_for_backup()
        slave = self.agency._broker.slaves.values()[0]

        self.info('killing slave')
        d = slave.callRemote('shutdown', stop_process=True)
        self.assertFailure(d, pb.PBConnectionLost)
        yield d
        yield common.delay(None, 0.5)
        yield self.wait_for_backup()
        slave2 = self.agency._broker.slaves.values()[0]
        self.assertNotEqual(slave.slave_id, slave2.slave_id)

    @common.attr(shutdown=False)
    @defer.inlineCallbacks
    def testUpgrade(self):
        self.agency.config['agency']['enable_spawning_slave'] = False
        yield self.agency.initiate()
        if os.path.exists("effect.tmp"):
            os.unlink("effect.tmp")
        upgrade_cmd = 'touch effect.tmp'
        yield self.agency.upgrade(upgrade_cmd, testing=True)
        self.assertTrue(os.path.exists("effect.tmp"))

    def spawn_agency(self):
        cmd, cmd_args, env = self.get_cmd_line()

        p = standalone.Process(self, cmd, cmd_args, env)
        return p.restart()

    def get_cmd_line(self):
        command = 'feat'
        args = ['--no-slave',
                '--msghost', self.msg_host,
                '--msgport', str(self.msg_port),
                '--msguser', 'guest',
                '--msgpass', 'guest',
                '--dbhost', self.db_host,
                '--dbport', str(self.db_port),
                '--dbname', self.db_name,
                '--jourfile', self.jourfile,
                '--rundir', os.path.abspath(os.path.curdir),
                '--logdir', os.path.abspath(os.path.curdir),
                '--socket-path', self.socket_path]
        python_path = ":".join(sys.path)
        env = dict(PYTHONPATH=python_path,
                   FEAT_DEBUG=log.FluLogKeeper.get_debug(),
                   PATH=os.environ.get("PATH"))

        return command, args, env

    @defer.inlineCallbacks
    def tearDown(self):
        yield self.wait_for(self.agency.is_idle, 20)
        if self.shutdown:
            yield self.agency.full_shutdown()
        yield self.db_process.terminate()
        yield self.msg_process.terminate()
        yield common.TestCase.tearDown(self)

    @defer.inlineCallbacks
    def assert_has_logs(self, agent_type, agent_id):
        jour = self.agency._journaler._writer
        yield self.wait_for(jour.is_idle, 10)
        logs = yield jour.get_log_entries(filters=[dict(category=agent_type,
                                                        name=agent_id,
                                                        level=5)])
        self.assertTrue(len(logs) > 0)

    @defer.inlineCallbacks
    def assert_journal_contains(self, agent_ids):
        jour = self.agency._journaler
        yield self.wait_for(jour.is_idle, 10)
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

    def wait_for_pid(self, pid_path):

        def pid_created():
            return os.path.exists(pid_path)

        return self.wait_for(pid_created, timeout=20)

    def wait_for_slave(self, timeout=20):

        def is_slave():
            return self.agency._broker.is_slave()

        return  self.wait_for(is_slave, timeout)

    def wait_for_master(self, timeout=20):

        def became_master():
            return self.agency._broker.is_master()

        return self.wait_for(became_master, timeout)

    def wait_for_backup(self, timeout=20):
        return self.wait_for(self.agency._broker.has_slave, timeout)
