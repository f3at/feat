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

    timeout = 10

    def expired(self):
        '''@see L{IAgentTask}'''

    @replay.immutable
    def finished(self, state):
        return state.medium.finished()
