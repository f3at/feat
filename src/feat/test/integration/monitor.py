from feat.agents.base import agent, replay, descriptor
from feat.agents.common import monitor
from feat.common import manhole


@agent.register('request_monitor_agent')
class RequestMontitorAgent(agent.BaseAgent):

    @manhole.expose()
    @replay.mutable
    def request_monitor(self, state):
        return monitor.request_monitor(self)


@descriptor.register('request_monitor_agent')
class Descriptor(descriptor.Descriptor):
    pass
