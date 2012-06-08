import os

from feat.common import fiber, error

from feat.agents.base import agent, collector, descriptor, replay
from feat.agents.common import monitor, export
from feat.process.base import ProcessState
from feat.process import standalone

from feat.agents.application import feat


@feat.register_descriptor("nagios_agent")
class Descriptor(descriptor.Descriptor):

    # this can be a template using %(path)s variable
    descriptor.field("update_command", None)


@feat.register_agent('nagios_agent')
class NagiosAgent(agent.BaseAgent):

    restart_strategy = monitor.RestartStrategy.local

    migratability = export.Migratability.shutdown

    @replay.mutable
    def initiate(self, state, update_command=None):
        i = state.medium.register_interest(ConfigCollector)
        i.bind_to_lobby()

        desc = self.get_descriptor()
        state.update_command = update_command or desc.update_command
        return self._save_config()

    @replay.journaled
    def config_changed(self, state, origin, body):
        filename = 'nagios_%s.cfg' % (origin.key, )
        path = os.path.abspath(filename)
        self.info("Received new nagios config, saving it to %s", path)
        self._save_file(path, body)

        f = fiber.succeed()
        if not state.update_command:
            self.info("Agent configured without update_command, ignoring.")
        else:
            command = state.update_command % dict(path=path)
            parts = command.split(' ')
            p = standalone.Process(self, parts[0], parts[1:], self._environ())
            f.add_callback(fiber.drop_param, p.restart)
            f.add_callback(fiber.drop_param, p.wait_for_state,
                           ProcessState.finished, ProcessState.failed)
        f.add_callback(fiber.drop_param, self._remove_file, path)
        f.add_callback(fiber.drop_param, self.call_remote, origin,
                       'push_notifications')
        return f

    ### private ###

    @replay.side_effect
    def _environ(self):
        return os.environ

    @agent.update_descriptor
    def _save_config(self, state, desc):
        desc.update_command = state.update_command

    @replay.side_effect
    def _save_file(self, path, body):
        with open(path, 'w') as f:
            f.write(body)

    @replay.side_effect
    def _remove_file(self, path):
        try:
            os.unlink(path)
        except Exception as e:
            error.handle_exception(self, e, 'Failed to remove file: %s', path)


class ConfigCollector(collector.BaseCollector):

    protocol_id = 'nagios-config'

    @replay.immutable
    def notified(self, state, msg):
        origin, body = msg.payload
        return state.agent.config_changed(origin, body)
