from zope.interface import implements, classProvides

from feat.agents.base import replay, task, poster, labour
from feat.common import serialization, fiber, error_handler

from feat.agents.monitor.interface import *
from feat.interface.agent import *
from feat.interface.task import *


@serialization.register
class Pacemaker(labour.BaseLabour):

    classProvides(IPacemakerFactory)
    implements(IPacemaker)

    log_category = "pacemaker"

    def __init__(self, patron, monitor, period=None):
        labour.BaseLabour.__init__(self, IAgent(patron))
        self._monitor = monitor
        self._period = period or DEFAULT_HEARTBEAT_PERIOD

    @replay.side_effect
    def initiate(self):
        agent = self.patron

        self.debug("Starting agent %s pacemaker for monitor %s "
                   "with %s sec period",
                   agent.get_full_id(), self._monitor, self._period)

        poster = agent.initiate_protocol(HeartBeatPoster, self._monitor)
        self._task = agent.initiate_task(HeartBeatTask, poster, self._period)

    @replay.side_effect
    def cleanup(self):
        self.debug("Stopping agent %s pacemaker for monitor %s",
                   self.patron.get_full_id(), self._monitor)
        self._task.cancel()


@serialization.register
class FakePacemaker(labour.BaseLabour):

    classProvides(IPacemakerFactory)
    implements(IPacemaker)

    log_category = "pacemaker"

    def __init__(self, patron, monitor, period):
        labour.BaseLabour.__init__(self, IAgent(patron))

    @replay.side_effect
    def initiate(self):
        """Nothing."""

    @replay.side_effect
    def cleanup(self):
        """Nothing."""


class HeartBeatPoster(poster.BasePoster):

    protocol_id = 'heart-beat'

    ### Overridden Methods ###

    @replay.immutable
    def pack_payload(self, state, index):
        desc = state.agent.get_descriptor()
        return desc.doc_id, desc.instance_id, index


class HeartBeatTask(task.BaseTask):

    timeout = 0

    @replay.mutable
    def initiate(self, state, poster, period):
        state.index = 0
        state.next = None
        state.canceled = False
        state.poster = poster
        state.period = period
        return self.beat()

    @replay.mutable
    def cancel(self, state):
        self.debug("Stopping pacemaker")
        if state.canceled:
            return fiber.succeed(self)

        state.canceled = True
        if state.next:
            state.agent.cancel_delayed_call(state.next)
            state.next = None

        state.medium.finish(self)

    @replay.mutable
    def beat(self, state):
        assert not state.canceled, "Cannot beat, task canceled"

        self.log("Deliver impulse %d", state.index)
        state.poster.notify(state.index)
        state.index += 1

        state.next = state.agent.call_later(state.period, self.beat)
        return NOT_DONE_YET
