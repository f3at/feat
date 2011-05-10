from zope.interface import implements, classProvides

from feat.agents.base import replay, task, poster, labour
from feat.common import serialization, fiber, error_handler

from feat.agencies import periodic
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
        self._task = None

    @replay.side_effect
    def startup(self):
        agent = self.patron

        self.debug("Starting agent %s pacemaker for monitor %s "
                   "with %s sec period",
                   agent.get_full_id(), self._monitor, self._period)

        poster = agent.initiate_protocol(HeartBeatPoster, self._monitor)

        f = periodic.PeriodicProtocolFactory(HeartBeatTask,
                                             period=self._period,
                                             busy=False)
        self._task = agent.initiate_protocol(f, poster)

    @replay.side_effect
    def cleanup(self):
        self.debug("Stopping agent %s pacemaker for monitor %s",
                   self.patron.get_full_id(), self._monitor)
        if self._task is not None:
            self._task.cancel()

    def __hash__(self):
        return hash(self._monitor)

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return self._monitor == other._monitor

    def __ne__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return self._monitor != other._monitor


@serialization.register
class FakePacemaker(labour.BaseLabour):

    classProvides(IPacemakerFactory)
    implements(IPacemaker)

    log_category = "pacemaker"

    def __init__(self, patron, monitor, period=None):
        labour.BaseLabour.__init__(self, IAgent(patron))

    @replay.side_effect
    def startup(self):
        """Nothing."""

    @replay.side_effect
    def cleanup(self):
        """Nothing."""


class HeartBeatPoster(poster.BasePoster):

    protocol_id = 'heart-beat'

    ### Overridden Methods ###

    @replay.immutable
    def pack_payload(self, state):
        desc = state.agent.get_descriptor()
        return desc.doc_id, desc.instance_id


class HeartBeatTask(task.BaseTask):

    timeout = 5
    protocol_id = "heart-beat"

    @replay.mutable
    def initiate(self, state, poster):
        poster.notify()
