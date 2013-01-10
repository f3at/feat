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
import copy

from feat.process import base
from feat.agents.base import replay
from feat.common.text_helper import format_block


class Process(base.Base):

    def configure(self):
        self.config = dict()
        workspace = self.get_tmp_dir()
        self.config['workspace'] = workspace
        self.config['tempdir'] = os.path.join(workspace, 'couch_db')
        self.config['port'] = self.get_free_port()
        self.config['log'] = os.path.join(workspace, 'couch_test.log')
        self.config['local_ini'] = os.path.join(workspace, 'local.ini')
        self.config['host'] = '127.0.0.1'
        couchpy = base.which('feat-couchpy', os.environ['PATH'])
        if not couchpy:
            # workaround to work with tests (when we don't have bin in path)
            import feat
            bin_path = os.path.abspath(os.path.join(
                feat.__path__[0], '..', '..', 'bin'))
            couchpy = base.which('feat-couchpy', bin_path)
            if couchpy is None:
                raise base.DependencyError(
                    'feat-couchpy script is not in a path')

        self.config['couchpy'] = couchpy

    @replay.side_effect
    def prepare_workspace(self):
        shutil.rmtree(self.config['tempdir'], ignore_errors=True)

        tmpl_path = os.path.join(os.path.dirname(__file__),
                                 'local.ini.template')
        handle = open(tmpl_path)

        f = file(self.config['local_ini'], 'w')
        f.write(handle.read() % self.config)
        f.close()
        os.mkdir(self.config['tempdir'])
        os.mkdir(os.path.join(self.config['tempdir'], 'lib'))
        os.mkdir(os.path.join(self.config['tempdir'], 'log'))

    def initiate(self):
        self.configure()
        self.prepare_workspace()

        self.command = base.which('couchdb', os.environ['PATH'])
        self.env = copy.deepcopy(os.environ)
        self.args = ['-a', self.config['local_ini']]
        self.keep_workdir = False

    def terminate(self, keep_workdir=False):
        self.keep_workdir = keep_workdir
        return base.Base.terminate(self)

    @replay.side_effect
    def started_test(self):
        buffer = self._control.out_buffer
        self.log("Checking buffer: %s", buffer)
        return "Apache CouchDB has started on http://127.0.0.1:" in buffer

    @replay.side_effect
    def on_finished(self, e):
        if not self.keep_workdir:
            shutil.rmtree(self.get_config()['workspace'], ignore_errors=True)
        base.Base.on_finished(self, e)
