# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.python import components, failure
from zope.interface import implements

from feat.interface import task, protocols
from feat.common import log, enum, fiber, delay, error_handler, serialization

from feat.agencies.interface import IAgencyInitiatorFactory, IListener

from feat.agencies import common


class AgencyTaskFactory(object):

    implements(IAgencyInitiatorFactory)

    type_name = 'task-medium-factory'

    def __init__(self, factory):
        self._factory = factory

    def __call__(self, agent, recipients, *args, **kwargs):
        return AgencyTask(agent, *args, **kwargs)


components.registerAdapter(AgencyTaskFactory,
                           task.ITaskFactory,
                           IAgencyInitiatorFactory)


class TaskState(enum.Enum):
    '''
    performing - Task is running
    completed - Task is finished
    error - Task has an error
    expired - Task timeout
    '''

    (performing, completed, expired, error) = range(4)


class AgencyTask(log.LogProxy, log.Logger, common.StateMachineMixin,
                 common.ExpirationCallsMixin, common.AgencyMiddleMixin,
                 common.InitiatorMediumBase):

    implements(task.IAgencyTask, serialization.ISerializable, IListener)

    log_category = 'agency-task'

    type_name = 'task-medium'

    def __init__(self, agent, *args, **kwargs):
        log.Logger.__init__(self, agent)
        log.LogProxy.__init__(self, agent)
        common.StateMachineMixin.__init__(self)
        common.ExpirationCallsMixin.__init__(self)
        common.AgencyMiddleMixin.__init__(self)
        common.InitiatorMediumBase.__init__(self)

        self.agent = agent
        self.args = args
        self.kwargs = kwargs

    #IAgencyTask

    def initiate(self, task):
        self.task = task
        self.log_name = self.task.__class__.__name__

        self._set_state(TaskState.performing)

        self._cancel_expiration_call()
        timeout = self.agent.get_time() + self.task.timeout
        error = protocols.InitiatorExpired(
                'Timeout exceeded waiting for task.initate()')
        self._expire_at(timeout, self._expired,
                TaskState.expired, failure.Failure(error))

        d = fiber.maybe_fiber(self.task.initiate, *self.args, **self.kwargs)
        d.addCallbacks(self._completed, self._error)
        return task

    def get_session_id(self):
        return self.session_id

    def get_agent_side(self):
        return self.task

    #ISerializable

    def snapshot(self):
        return id(self)

    # Used by ExpirationCallsMixin

    def _get_time(self):
        return self.agent.get_time()

    #Private section

    def _completed(self, arg):
        self._set_state(TaskState.completed)
        delay.callLater(0, self._terminate, arg)

    def _error(self, arg):
        self._set_state(TaskState.error)
        delay.callLater(0, self._terminate, arg)

    def _expired(self, arg):
        self._set_state(TaskState.expired)
        d = fiber.maybe_fiber(self.task.expired)
        return d

    def _terminate(self, arg):
        common.ExpirationCallsMixin._terminate(self)

        self.log("Unregistering task %s" % self.session_id)
        self.agent.unregister_listener(self.session_id)

        common.InitiatorMediumBase._terminate(self, arg)
