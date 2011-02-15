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
        buffer = self.control.out_buffer
        self.log("Checking buffer: %s", buffer)
        return "Agency is ready. Agent started." in buffer

    def restart(self):
        d = base.Base.restart(self)
        return d

    @replay.immutable
    def on_ready(self, state, out_buffer):
        base.Base.on_ready(self, out_buffer)
        state.agency.append_process(self)

    @replay.immutable
    def on_finished(self, state, exception):
        state.agency.remove_process(self)

    @replay.immutable
    def on_failed(self, state, exception):
        state.agency.remove_process(self)
