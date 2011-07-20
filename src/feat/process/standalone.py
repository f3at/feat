from feat.process import base
from feat.agents.base import replay


class Process(base.Base):

    def initiate(self, command, args, env):
        self.command = command
        self.args = args
        self.env = env

    def started_test(self):
        # Process should deamonize itself.
        return True

    def restart(self):
        d = base.Base.restart(self)
        # This fakes process output and is needed because it might deamonize
        # itself without puting anything to stdout.
        self._control.outReceived("")
        return d
