import shutil
import os

from feat.process import base
from feat.agents.base import replay
from feat.common import format_block


class Process(base.Base):

    @replay.mutable
    def configure(self, state):
        state.config = dict()
        workspace = self.get_tmp_dir()
        state.config['workspace'] = workspace
        state.config['dir'] = os.path.join(workspace, 'couch_db')
        state.config['port'] = self.get_free_port()
        state.config['log'] = os.path.join(workspace, 'couch_test.log')
        state.config['local_ini'] = os.path.join(workspace, 'local.ini')
        state.config['host'] = '127.0.0.1'

    @replay.side_effect
    @replay.immutable
    def prepare_workspace(self, state):
        local_ini_tmpl = format_block("""
        [couchdb]
        database_dir = %(dir)s
        view_index_dir = %(dir)s

        [httpd]
        port = %(port)d

        [log]
        file = %(log)s
        """)
        shutil.rmtree(state.config['dir'], ignore_errors=True)

        f = file(state.config['local_ini'], 'w')
        f.write(local_ini_tmpl % state.config)
        f.close()

    @replay.mutable
    def initiate(self, state):
        self.configure()
        self.prepare_workspace()

        state.command = '/usr/bin/couchdb'
        state.env['HOME'] = os.environ['HOME']
        state.args = ['-a', state.config['local_ini']]

    @replay.side_effect
    def started_test(self):
        buffer = self.control.out_buffer
        self.log("Checking buffer: %s", buffer)
        return "Apache CouchDB has started on http://127.0.0.1:" in buffer

    @replay.side_effect
    def on_finished(self, e):
        shutil.rmtree(self.get_config()['workspace'], ignore_errors=True)
        base.Base.on_finished(self, e)
