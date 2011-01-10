import shutil
import os
import uuid

from feat.process import base


class Process(base.Base):

    def configure(self):
        self.config = dict()
        workspace = self.get_tmp_dir()
        self.config['port'] = self.get_free_port()
        self.config['node_name'] = str(uuid.uuid1())
        self.config['workspace'] = workspace
        self.config['mnesia_dir'] =\
             os.path.join(workspace, 'rabbitmq-rabbit-mnesia')

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

    def started_test(self):
        buffer = self.control.out_buffer
        self.log("Checking buffer: %s", buffer)
        return "broker running" in buffer

    def rabbitmqctl(self, command):
        process = RabbitMQCtl(self.env, command)
        process.restart()

        return process.wait_for_state(base.ProcessState.finished)

    def rabbitmqctl_dump(self, command):
        d = self.rabbitmqctl(command)
        d.addCallback(lambda output:
                      self.log("Output of command 'rabbitmqctl %s':\n%s\n",
                               command, output))
        return d

    def on_finished(self, e):
        shutil.rmtree(self.config['workspace'], ignore_errors=True)
        base.Base.on_finished(self, e)


class RabbitMQCtl(base.Base):

    def __init__(self, env, arg_line):
        base.Base.__init__(self)

        self.env = env
        self.args = arg_line.split()

    def started_test(self):
        return True

    def initiate(self):
        self.command = '/usr/lib/rabbitmq/bin/rabbitmqctl'
