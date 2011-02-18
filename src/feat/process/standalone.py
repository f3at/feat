from feat.process import base
from feat.agents.base import replay


class Process(base.Base):

    log_name = "standalone"

    def init_state(self, state, agency, machine_state, command, args, env):
        base.Base.init_state(self, state, agency, machine_state)
        state.agency = agency
        state.command = command
        state.args = args
        state.env = env

    def initiate(self):
        # Just pass here. All the configuration has
        # been done on creation time.
        pass

    def started_test(self):
        # Process should deamonize itself.
        return True

    def restart(self):
        d = base.Base.restart(self)
        # This fakes process output and is needed because it might deamonize
        # itself without puting anything to stdout.
        self.control.outReceived("")
        return d
