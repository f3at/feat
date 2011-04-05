from feat.common import serialization, defer, fiber
from feat.agents.base import replay


@serialization.register
class AgentNotifier(defer.Notifier, serialization.Serializable):

    def __init__(self, agent):
        defer.Notifier.__init__(self)
        self.agent = agent

    def wait(self, notification):
        return fiber.wrap_defer(defer.Notifier.wait, self, notification)

    def callback(self, notification, result):
        self.agent.call_next(defer.Notifier.callback,
                             self, notification, result)

    def errback(self, notification, failure):
        self.agent.call_next(defer.Notifier.errback,
                             self, notification, failure)

    def __eq__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return True

    def __ne__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return False


class AgentMixin(object):

    # FIXME: Here it would be better to use @replay.mutable
    # but it fails with:

    # Failed to register function <function initiate at 0x9dfde2c> with
    # name 'feat.agents.host.host_agent.HostAgent.initiate' it is already
    # used by function <function initiate at 0x9e216f4>

    # This is probably a bug in annotations

    def initiate(self, state):
        state.notifier = AgentNotifier(self)

    @replay.immutable
    def wait_for_event(self, state, name):
        return state.notifier.wait(name)

    @replay.immutable
    def callback_event(self, state, name, value):
        state.notifier.callback(name, value)

    @replay.immutable
    def errback_event(self, state, name, failure):
        state.notifier.errback(name, failure)
