import shutil
import os
import uuid

from feat.process import base
from feat.agents.base import replay
from feat.common import fiber


class Process(base.Base):

    @replay.mutable
    def configure(self, state):
        state.config = dict()
        workspace = self.get_tmp_dir()
        state.config['port'] = self.get_free_port()
        state.config['node_name'] = str(uuid.uuid1())
        state.config['workspace'] = workspace
        state.config['mnesia_dir'] =\
             os.path.join(workspace, 'rabbitmq-rabbit-mnesia')

    @replay.side_effect
    @replay.immutable
    def prepare_workspace(self, state):
        shutil.rmtree(state.config['mnesia_dir'], ignore_errors=True)

    @replay.mutable
    def initiate(self, state):
        self.configure()
        self.prepare_workspace()

        state.command = '/usr/lib/rabbitmq/bin/rabbitmq-server'

        state.env['HOME'] = os.environ['HOME']
        state.env['RABBITMQ_NODE_PORT'] = str(state.config['port'])
        state.env['RABBITMQ_NODENAME'] = str(state.config['node_name'])
        state.env['RABBITMQ_MNESIA_DIR'] = state.config['mnesia_dir']
        state.env['RABBITMQ_NODE_IP_ADDRESS'] = '127.0.0.1'
        state.env['RABBITMQ_LOG_BASE'] = state.config['workspace']
        state.env['RABBITMQ_PLUGINS_EXPAND_DIR'] = os.path.join(
            state.config['workspace'],
            'rabbitmq-rabbit-plugins-scratch')
        state.env['RABBITMQ_ALLOW_INPUT'] = 'true'
        state.env['RABBITMQ_SERVER_START_ARGS'] = ''

    @replay.side_effect
    def started_test(self):
        buffer = self.control.out_buffer
        self.log("Checking buffer: %s", buffer)
        return "broker running" in buffer

    @replay.journaled
    def rabbitmqctl(self, state, command):
        process = RabbitMQCtl(self, state.env, command)
        f = fiber.Fiber()
        f.add_callback(fiber.drop_result, process.restart)
        f.add_callback(fiber.drop_result, process.wait_for_state,
                       base.ProcessState.finished)
        f.succeed()
        return f

    def rabbitmqctl_dump(self, command):
        # TODO: Once upon a time a line below returns a Fiber instead of
        # Deferred. This is random and definitely should be investigated
        d = self.rabbitmqctl(command)
        d.addCallback(lambda output:
                      self.log("Output of command 'rabbitmqctl %s':\n%s\n",
                               command, output))
        return d

    @replay.side_effect
    def on_finished(self, e):
        shutil.rmtree(self.get_config()['workspace'], ignore_errors=True)
        base.Base.on_finished(self, e)


class RabbitMQCtl(base.Base):

    def init_state(self, state, agent, machine_state, env, arg_line):
        base.Base.init_state(self, state, agent, machine_state)
        state.env = env
        state.args = arg_line.split()

    def started_test(self):
        return True

    @replay.mutable
    def initiate(self, state):
        state.command = '/usr/lib/rabbitmq/bin/rabbitmqctl'
