from zope.interface import implements
from feat.interface import task
from feat.common import log, serialization, reflect
from feat.agents.base import protocol, replay


class Meta(type(replay.Replayable)):

    implements(task.ITaskFactory)

    def __init__(cls, name, bases, dct):
        cls.type_name = reflect.canonical_name(cls)
        serialization.register(cls)
        super(Meta, cls).__init__(name, bases, dct)


class BaseTask(log.Logger, protocol.InitiatorBase, replay.Replayable):
    """
    I am a base class for managers of tasks
    """

    __metaclass__ = Meta

    implements(task.IAgentTask)

    log_category = "task"
    protocol_type = "Task"
    protocol_id = None

    timeout = 10

    def __init__(self, agent, medium):
        log.Logger.__init__(self, medium)
        replay.Replayable.__init__(self, agent, medium)

    def init_state(self, state, agent, medium):
        state.agent = agent
        state.medium = medium

    @replay.immutable
    def restored(self, state):
        replay.Replayable.restored(self)
        log.Logger.__init__(self, state.medium)

    def initiate(self):
        '''@see L{task.IAgentTask}'''

    def expired(self):
        '''@see L{task.IAgentTask}'''
