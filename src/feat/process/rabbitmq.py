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
import shutil
import os
import uuid

from feat.process import base
from feat.agents.base import replay
from feat.common import defer


class Process(base.Base):

    def configure(self):
        self.config = dict()
        workspace = self.get_tmp_dir()
        self.config['port'] = self.get_free_port()
        self.config['node_name'] = str(uuid.uuid1())
        self.config['workspace'] = workspace
        self.config['mnesia_dir'] =\
             os.path.join(workspace, 'rabbitmq-rabbit-mnesia')

    @replay.side_effect
    def prepare_workspace(self):
        shutil.rmtree(self.config['mnesia_dir'], ignore_errors=True)

    def initiate(self):
        self.configure()
        self.prepare_workspace()

        self.command = '/usr/lib/rabbitmq/bin/rabbitmq-server'

        self.env['HOME'] = os.environ['HOME']
        self.env['RABBITMQ_NODE_PORT'] = str(self.config['port'])
        self.env['RABBITMQ_NODENAME'] = str(self.config['node_name'])
        self.env['RABBITMQ_MNESIA_DIR'] = self.config['mnesia_dir']
        self.env['RABBITMQ_NODE_IP_ADDRESS'] = '127.0.0.1'
        self.env['RABBITMQ_LOG_BASE'] = self.config['workspace']
        self.env['RABBITMQ_PLUGINS_EXPAND_DIR'] = os.path.join(
            self.config['workspace'],
            'rabbitmq-rabbit-plugins-scratch')
        self.env['RABBITMQ_ALLOW_INPUT'] = 'true'
        self.env['RABBITMQ_SERVER_START_ARGS'] = ''
        self.keep_workdir = False

    @replay.side_effect
    def started_test(self):
        buffer = self._control.out_buffer
        return "broker running" in buffer

    def rabbitmqctl(self, command):
        process = RabbitMQCtl(self, self.env, command)
        d = process.restart()
        d.addCallback(defer.drop_param,
            process.wait_for_state, base.ProcessState.finished)
        d.addCallback(defer.override_result, process.result)
        return d

    def rabbitmqctl_dump(self, command):
        d = self.rabbitmqctl(command)
        d.addCallback(lambda output:
                      self.log("Output of command 'rabbitmqctl %s':\n%s\n",
                               command, output))
        return d

    def terminate(self, keep_workdir=False):
        self.keep_workdir = keep_workdir
        return base.Base.terminate(self)

    @replay.side_effect
    def on_finished(self, e):
        if not self.keep_workdir:
            shutil.rmtree(self.get_config()['workspace'], ignore_errors=True)
        base.Base.on_finished(self, e)


class RabbitMQCtl(base.Base):

    def started_test(self):
        return True

    def initiate(self, env, arg_line):
        self.command = '/usr/lib/rabbitmq/bin/rabbitmqctl'
        self.env = env
        self.args = arg_line.split()
        self.result = defer.Deferred()

    def on_finished(self, exc):
        self.result.callback(self._control.out_buffer)

    def on_failed(self, exc):
        self.result.errback(exc)
