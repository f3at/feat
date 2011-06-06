from zope.interface import implements

from feat.agents.base import protocols, replay
from feat.common import serialization, reflect

from feat.interface.protocols import *
from feat.interface.task import *


class Meta(type(replay.Replayable)):

    implements(ITaskFactory)

    def __init__(cls, name, bases, dct):
        cls.type_name = reflect.canonical_name(cls)
        serialization.register(cls)
        super(Meta, cls).__init__(name, bases, dct)


class BaseTask(protocols.BaseInitiator):
    """
    I am a base class for managers of tasks
    """

    __metaclass__ = Meta

    implements(IAgentTask)

    log_category = "task"

    protocol_type = "Task"
    protocol_id = None
    busy = True # Busy tasks will not be idle

    timeout = 10

    @replay.immutable
    def cancel(self, state):
        state.medium.terminate()

    def expired(self):
        '''@see L{IAgentTask}'''

    @replay.immutable
    def finished(self, state):
        return state.medium.finished()


class StealthPeriodicTask(BaseTask):

    busy = False
    timeout = None

    def initiate(self, period):
        self._period = period
        self._call = None

        self._run()

        return NOT_DONE_YET

    def expired(self):
        self.cancel()

    @replay.immutable
    def cancel(self, state):
        self._cancel()
        state.medium.terminate()

    def run(self):
        """Overridden in sub-classes."""

    ### Private Methods ###

    def _run(self):
        self.run()
        self._schedule()

    @replay.immutable
    def _cancel(self, state):
        if self._call is not None:
            state.medium.cancel_delayed_call(self._call)
            self._call = None

    @replay.immutable
    def _schedule(self, state):
        self._cancel()
        self._call = state.medium.call_later_ex(self._period,
                                                self._run,
                                                busy=False)
