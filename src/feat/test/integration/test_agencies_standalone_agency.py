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
import os
import sys
import socket
import tempfile
import signal

from twisted.python import failure
from twisted.internet import defer
from twisted.trial.unittest import SkipTest

from feat.agencies.net import database
from feat.agencies.net import standalone as standalone_agency
from feat.agencies.net.broker import BrokerRole
from feat.agencies.interface import NotFoundError
from feat.agents.base import agent, descriptor, partners, dbtools
from feat.common import serialization, log, run, fcntl
from feat.process import standalone, rabbitmq, couchdb
from feat.process.base import DependencyError
from feat.test import common


class OptParseMock(object):
    agency_lock_path = ""
    agency_socket_path = ""


class StandalonePartners(partners.Partners):

    default_role = u'standalone'


@agent.register('standalone')
class StandaloneAgent(agent.BaseAgent):

    partners_class = StandalonePartners

    standalone = True

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
                '-D',
                '-X',
                '-a', agent_id]
        if s_kwargs:
            args += ['--kwargs', s_kwargs]
        path = ":".join([bin_path, os.environ["PATH"]])
        pythonpath = ":".join([src_path, os.environ.get("PYTHONPATH", "")])
        env = dict(PYTHONPATH=pythonpath, FEAT_DEBUG='5', PATH=path)
        return command, args, env


@descriptor.register('standalone')
class Descriptor(descriptor.Descriptor):
    pass


@common.attr('slow', timeout=100)
class IntegrationTestCase(common.TestCase):

    skip_coverage = True

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
        defer.setDebugging(True)
        common.TestCase.setUp(self)
        self.tempdir = os.path.curdir
        self.socket_path = os.path.join(os.path.curdir, 'feat-test.socket')

        bin_dir = os.path.abspath(os.path.join(
            os.path.curdir, '..', '..', 'bin'))
        os.environ["PATH"] = ":".join([bin_dir, os.environ["PATH"]])

        _, self.lock_path= tempfile.mkstemp()

        options = OptParseMock()
        options.agency_lock_path = self.lock_path
        options.agency_socket_path = self.socket_path
        self.agency = standalone_agency.Agency(options)

        try:
            self.db_process = couchdb.Process(self)
        except DependencyError:
            raise SkipTest("No CouchDB server found.")

        try:
            self.msg_process = rabbitmq.Process(self)
        except DependencyError:
            raise SkipTest("No RabbitMQ server found.")

        self.msg_host, self.msg_port = yield self._run_and_configure_msg()
        self.db_host, self.db_port, self.db_name =\
                          yield self._run_and_configure_db()

        self.pid_path = os.path.join(os.path.curdir, 'feat.pid')
        hostname = unicode(socket.gethostbyaddr(socket.gethostname())[0])

        yield self.spawn_agency()
        yield self.wait_for_pid(self.pid_path)

        def host_descriptor():

            def check(host_desc):
                return host_desc.instance_id == 1

            d = self.db.get_document(hostname)
            d.addCallbacks(check, failure.Failure.trap,
                           errbackArgs=(NotFoundError, ))
            return d

        yield self.wait_for(host_descriptor, 5)

    @defer.inlineCallbacks
    def tearDown(self):
        yield self.wait_for(self.agency.is_idle, 20)
        yield self.agency.shutdown(stop_process=False)
        yield self.db_process.terminate()
        yield self.msg_process.terminate()
        yield common.TestCase.tearDown(self)
        pid = run.get_pid(os.path.curdir)
        if pid is not None:
            run.signal_pid(pid, signal.SIGUSR2)

    @defer.inlineCallbacks
    def testMasterKilledWithOneStandalone(self):
        yield self.agency.initiate()
        yield self.wait_for_slave()

        pid = run.get_pid(os.path.curdir)
        run.term_pid(pid)
        yield self.wait_for_master_gone()
        yield self.wait_for_master_back()
        # we should have a pid now
        yield self.wait_for_pid(self.pid_path)


    @defer.inlineCallbacks
    def testLockAlreadyTaken(self):
        self.lock_fd = open(self.lock_path, 'rb+')
        if not fcntl.lock(self.lock_fd):
            self.fail("Could not take the lock")

        yield self.agency.initiate()
        yield self.wait_for_slave()

        pid = run.get_pid(os.path.curdir)
        run.term_pid(pid)
        yield self.wait_for_master_gone()
        yield common.delay(None, 10)
        pid = run.get_pid(os.path.curdir)
        self.assertTrue(pid is None)

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
                '--rundir', os.path.abspath(os.path.curdir),
                '--logdir', os.path.abspath(os.path.curdir),
                '--socket-path', self.socket_path,
                '--lock-path', self.lock_path,
                '-D']
        python_path = ":".join(sys.path)
        env = dict(PYTHONPATH=python_path,
                   FEAT_DEBUG=log.FluLogKeeper.get_debug(),
                   PATH=os.environ.get("PATH"))

        return command, args, env

    def wait_for_slave(self, timeout=20):

        def is_slave():
            return self.agency._broker.is_slave()

        return  self.wait_for(is_slave, timeout)

    def wait_for_pid(self, pid_path):

        def pid_created():
            return os.path.exists(pid_path)

        return self.wait_for(pid_created, timeout=20)

    def wait_for_master_gone(self, timeout=20):
        def broker_disconnected():
            return self.agency._broker.state == BrokerRole.disconnected

        return self.wait_for(broker_disconnected, timeout)

    def wait_for_master_back(self, timeout=20):
        def broker_connected():
            return self.agency._broker.state == BrokerRole.slave

        return self.wait_for(broker_connected, timeout)
