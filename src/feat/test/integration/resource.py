from feat.agents.base import agent, replay, descriptor
from feat.agents.common import raage
from feat.common import manhole


@agent.register('requesting_agent')
class RequestingAgent(agent.BaseAgent):

    @manhole.expose()
    @replay.mutable
    def request_resource(self, state, **resources):
        self.info('Requesting resoruce %r', resources)
        return raage.allocate_resource(self, resources)


@descriptor.register('requesting_agent')
class Descriptor(descriptor.Descriptor):
    pass
