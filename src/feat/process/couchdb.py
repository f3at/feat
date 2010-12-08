import shutil
import os

from feat.process import base
from feat.common import format_block


class Process(base.Base):

    def configure(self):
        self.config = dict()
        workspace = self.get_tmp_dir()
        self.config['workspace'] = workspace
        self.config['dir'] = os.path.join(workspace, 'couch_db')
        self.config['port'] = self.get_free_port()
        self.config['log'] = os.path.join(workspace, 'couch_test.log')
        self.config['local_ini'] = os.path.join(workspace, 'local.ini')
        self.config['host'] = '127.0.0.1'

    def prepare_workspace(self):
        local_ini_tmpl = format_block("""
        [couchdb]
        database_dir = %(dir)s
        view_index_dir = %(dir)s

        [httpd]
        port = %(port)d

        [log]
        file = %(log)s
        """)
        shutil.rmtree(self.config['dir'], ignore_errors=True)

        f = file(self.config['local_ini'], 'w')
        f.write(local_ini_tmpl % self.config)
        f.close()

    def initiate(self):
        self.configure()
        self.prepare_workspace()

        self.command = '/usr/bin/couchdb'
        self.env['HOME'] = os.environ['HOME']
        self.args = ['-a', self.config['local_ini']]

    def started_test(self):
        buffer = self.control.out_buffer
        self.log("Checking buffer: %s", buffer)
        return "Apache CouchDB has started on http://127.0.0.1:" in buffer

    def on_finished(self, e):
        shutil.rmtree(self.config['workspace'], ignore_errors=True)
        base.Base.on_finished(self, e)
