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
import sys
import os
import operator
import re

from twisted.python import failure
from twisted.spread import pb

from feat.test import common
from feat.test.integration.common import FullIntegrationTest, ModelTestMixin
from feat.process import standalone
from feat.agencies import agency as base_agency
from feat.agencies.net import agency, broker, config

from feat.agents.base import agent, descriptor, replay
from feat.common import serialization, fiber, log, first, run, defer
from feat.utils import host_restart
from feat.agents.application import feat

from feat.interface.agent import AgencyAgentState
from feat.database.interface import NotFoundError


class StandalonePartners(agent.Partners):

    default_role = u'standalone'


@feat.register_agent('standalone')
class StandaloneAgent(agent.BaseAgent):

    partners_class = StandalonePartners

    standalone = True

    # we are not testing monitoring here
    need_local_monitoring = False

    @staticmethod
    def get_cmd_line(desc, **kwargs):
        src_path = os.path.abspath(os.path.join(
            os.path.dirname(__file__), '..', '..', '..'))
        bin_path = os.path.abspath(os.path.join(
            src_path, '..', 'bin'))

        agent_id = str(desc.doc_id)
        s_kwargs = serialization.json.serialize(kwargs)

        command = 'feat'
        args = ['-i', 'feat.test.integration.test_agencies_net_agency',
                '-L', os.path.curdir,
                '-R', os.path.curdir,
                '-X',
                '--agent-id', agent_id]
        if s_kwargs:
            args += ['--kwargs', s_kwargs]
        path = ":".join([bin_path, os.environ["PATH"]])
        pythonpath = ":".join([src_path, os.environ.get("PYTHONPATH", "")])
        env = dict(PYTHONPATH=pythonpath, FEAT_DEBUG='5', PATH=path)
        return command, args, env


@feat.register_descriptor('standalone')
class Descriptor(descriptor.Descriptor):
    pass


@feat.register_agent('standalone_with_args')
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


@feat.register_descriptor('standalone_with_args')
class DescriptorWithArgs(descriptor.Descriptor):
    pass


@feat.register_agent('standalone-master')
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


@feat.register_descriptor('standalone-master')
class MasterDescriptor(descriptor.Descriptor):
    pass


@common.attr('slow', timeout=40)
class IntegrationTestCase(FullIntegrationTest, ModelTestMixin):

    skip_coverage = True
    configurable_attributes = ['run_rabbit', 'run_couch', 'shutdown']
    run_rabbit = True
    run_couch = True
    shutdown = True

    @defer.inlineCallbacks
    def setUp(self):
        yield FullIntegrationTest.setUp(self)

        journal_connstr = "sqlite://%s" % (self.jourfile, )
        c = config.Config(
            msg=config.MsgConfig(host=self.msg_host, port=self.msg_port),
            db=config.DbConfig(host=self.db_host, port=self.db_port,
                               name=self.db_name),
            agency=config.AgencyConfig(
                journal=[journal_connstr],
                rundir=self.tempdir,
                logdir=self.tempdir,
                socket_path=self.socket_path))
        c.load(dict())
        self.agency = agency.Agency(c)

    @common.attr(skip="find_agent is broken")
    @defer.inlineCallbacks
    def testStartStandaloneAgent(self):
        yield self.agency.initiate()
        yield self.wait_for_host_agent(20)
        host_a = self.agency.get_host_agent()
        yield host_a.wait_for_ready()
        self.info("Host agent is ready, starting standalone agent.")

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
        self.assertIsInstance(stand, broker.AgentReference)

        slave = first(x for x in self.agency._broker.slaves.itervalues()
                      if x.is_standalone)

        self.assertIsInstance(slave, broker.SlaveReference)
        host = yield slave.callRemote('find_agent', agent_ids[0])
        self.assertIsInstance(host, base_agency.AgencyAgent)
        stand = yield slave.callRemote('find_agent', agent_ids[1])
        self.assertIsInstance(stand, broker.AgentReference)

        not_found = yield slave.callRemote('find_agent', 'unknown id')
        self.assertIs(None, not_found)

        # asserts on slaves registry
        self.assertEqual(2, len(self.agency._broker.slaves))
        self.assertEqual(1, len(slave.agents))
        self.assertEqual(agent_ids[1], slave.agents.keys()[0])

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

        self.info("Just before validating models.")
        yield self.validate_model_tree(self.agency)

    @defer.inlineCallbacks
    def testStartStandaloneArguments(self):
        yield self.agency.initiate()
        yield self.wait_for_host_agent(10)
        host_a = self.agency.get_host_agent()

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

        Only database server is necessary to run now. The messaging is
        configured at the end of the test to check that it gets connected.
        '''
        yield self.agency.initiate()
        self.assertEqual(None, self.agency._get_host_medium())
        self.info("Starting CouchDb.")
        db_host, db_port, db_name = yield self.run_and_configure_db()
        self.info("Reconfiguring the agencies database.")
        self.agency.reconfigure_database(db_host, db_port, db_name)

        yield self.wait_for_host_agent(80)
        medium = self.agency._get_host_medium()
        yield medium.wait_for_state(AgencyAgentState.ready)

        yield self.wait_for(self.agency.is_idle, 20)

        # now terminate the host agents by deleting his descriptor
        self.info("Killing host agent.")
        agent_id = medium.get_agent_id()
        desc = yield self.db.get_document(agent_id)
        old_shard = desc.shard

        yield self.db.delete_document(desc)

        yield medium.wait_for_state(AgencyAgentState.terminated)

        yield self.wait_for_host_agent(10)
        new_medium = self.agency._get_host_medium()
        yield new_medium.wait_for_state(AgencyAgentState.ready)

        new_shard = new_medium.get_shard_id()
        self.assertEqual(old_shard, new_shard)

        self.assertFalse(self.is_rabbit_connected())

        self.info("Starting RabbitMQ.")
        msg_host, msg_port = yield self.run_and_configure_msg()
        self.agency.reconfigure_messaging(msg_host, msg_port)

        yield common.delay(None, 5)
        output = yield self.msg_process.rabbitmqctl('list_exchanges')
        self.assertIn(new_medium.get_shard_id(), output)

        self.assertTrue(self.is_rabbit_connected())

    @common.attr(timeout=40)
    @defer.inlineCallbacks
    def testBackupAgency(self):
        pid_path = os.path.join(os.path.curdir, 'feat.pid')
        hostname = self.agency.get_hostname()

        yield self.spawn_agency()
        yield self.wait_for_pid(pid_path)

        def host_descriptor():

            def check(host_desc):
                return host_desc.instance_id == 1

            d = self.db.get_document(hostname)
            d.addCallbacks(check, failure.Failure.trap,
                           errbackArgs=(NotFoundError, ))
            return d

        yield self.wait_for(host_descriptor, 5)

        yield common.delay(None, 5)
        yield self.agency.initiate()
        yield self.wait_for_slave()

        pid = run.get_pid(os.path.curdir)

        run.term_pid(pid)
        # now cleanup the stale descriptors the way the monitor agent would

        yield self.wait_for_master()
        yield host_restart.do_cleanup(self.db, hostname)

        def has_host():
            m = self.agency._get_host_medium()
            return m is not None and m.is_ready()

        yield self.wait_for(has_host, 15)

        host_desc = yield self.db.get_document(hostname)
        # for host agent the instance id should not increase
        # (this is only the case for agents run by host agent)
        self.assertEqual(1, host_desc.instance_id)

        yield self.wait_for_backup()
        slave = self.agency._broker.slaves.values()[0]

        self.info('killing slave %s', slave.slave_id)
        d = slave.callRemote('shutdown', stop_process=True)
        self.assertFailure(d, pb.PBConnectionLost)
        yield d

        yield common.delay(None, 0.5)
        yield self.wait_for_backup()

        slave2 = self.agency._broker.slaves.values()[0]
        self.assertNotEqual(slave.slave_id, slave2.slave_id)

    @common.attr(shutdown=False,
                 skip="This test is running shutdown of the agency before"
                      "it was properly set up. Test the upgrades in some "
                      "other way or add proper delay here (which would be "
                      "an overkill in my opinion.")
    @defer.inlineCallbacks
    def testUpgrade(self):
        self.agency.config['agency']['enable_spawning_slave'] = False
        yield self.agency.initiate()
        yield self.wait_for_host_agent(20)
        yield self.wait_for(self.agency.is_idle, 20)

        if os.path.exists("effect.tmp"):
            os.unlink("effect.tmp")
        upgrade_cmd = 'touch effect.tmp'
        yield self.agency.upgrade(upgrade_cmd, testing=True)
        yield self.wait_for(self.agency.is_idle, 20)
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
                '--journal', "sqlite://%s" % (self.jourfile, ),
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
        if self.shutdown:
            yield self.agency.full_shutdown()
        yield FullIntegrationTest.tearDown(self)

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
        self.info("Starting waiting for journal to be idle, jour=%r", jour)
        yield self.wait_for(jour.is_idle, 15)
        resp = yield jour._writer.get_histories()
        ids_got = map(operator.attrgetter('agent_id'), resp)
        set1 = set(agent_ids)
        set2 = set(ids_got)
        self.assertTrue(set1.issubset(set2),
                        "%r is not subset of %r" % (set1, set2, ))

    def is_rabbit_connected(self):
        s = self.agency.show_connections()
        return re.search('RabbitMQ\s+True', s) is not None
