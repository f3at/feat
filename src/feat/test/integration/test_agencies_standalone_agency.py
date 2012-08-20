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

from feat.agencies.net import standalone as standalone_agency, config
from feat.agencies.net.broker import BrokerRole
from feat.database.interface import NotFoundError
from feat.common import log, run, fcntl
from feat.process import standalone
from feat.test import common
from feat.test.integration.common import FullIntegrationTest


class OptParseMock(object):
    agency_lock_path = ""
    agency_socket_path = ""
    agency_rundir = ""


@common.attr('slow', timeout=40)
class FullIntegrationTestCase(FullIntegrationTest):

    skip_coverage = True
    start_couch = True
    start_rabbit = True
    run_rabbit = True
    run_couch = True

    @defer.inlineCallbacks
    def setUp(self):
        yield FullIntegrationTest.setUp(self)

        _, self.lock_path= tempfile.mkstemp()

        options = OptParseMock()
        options.agency_lock_path = self.lock_path
        options.agency_socket_path = self.socket_path
        options.agency_journal = ["sqlite://%s" % (self.jourfile, )]
        options.agency_rundir = os.path.abspath(os.path.curdir)
        c = config.Config()
        c.load(dict(), options)
        self.agency = standalone_agency.Agency(c)

        yield self.spawn_agency()
        yield self.wait_for_pid(self.pid_path)

        def host_descriptor():

            def check(host_desc):
                return host_desc.instance_id == 1

            d = self.db.get_document(hostname)
            d.addCallbacks(check, failure.Failure.trap,
                           errbackArgs=(NotFoundError, ))
            return d

        hostname = self.agency.get_hostname()
        yield self.wait_for(host_descriptor, 5)

    @defer.inlineCallbacks
    def tearDown(self):
        yield self.agency.shutdown(stop_process=False)
        yield FullIntegrationTest.tearDown(self)
        pid = run.get_pid(os.path.curdir)
        if pid is not None:
            run.signal_pid(pid, signal.SIGUSR2)

    @defer.inlineCallbacks
    def testMasterKilledWithOneStandalone(self):
        yield self.agency.initiate()
        yield self.wait_for(self.agency.is_idle, 20)
        yield self.wait_for_slave()

        self.info('terminating master')
        pid = run.get_pid(os.path.curdir)
        run.term_pid(pid)
        yield self.wait_for_master_gone()
        yield self.wait_for_master_back()
        # we should have a pid now
        yield self.wait_for_pid(self.pid_path)
        yield self.wait_for(self.agency.is_idle, 20)

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

        # remove the lock so that the broker in our
        # agency can connect and stop retrying, overwise the test
        # will finish in undefined way (this is part of the teardown)
        fcntl.unlock(self.lock_fd)
        self.lock_fd.close()

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
                '--journal', "sqlite://%s" % (self.jourfile, ),
                '--socket-path', self.socket_path,
                '--lock-path', self.lock_path]
        python_path = ":".join(sys.path)
        env = dict(PYTHONPATH=python_path,
                   FEAT_DEBUG=log.FluLogKeeper.get_debug(),
                   PATH=os.environ.get("PATH"))

        return command, args, env

    def wait_for_master_gone(self, timeout=20):
        return self.agency._broker.wait_for_state(BrokerRole.disconnected)

    def wait_for_master_back(self, timeout=20):
        return self.agency._broker.wait_for_state(BrokerRole.slave)
