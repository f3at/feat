# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.python import components, failure
from zope.interface import implements

from feat.agencies import common, protocols
from feat.common import log, enum, fiber, defer, delay
from feat.common import error_handler, serialization

from feat.agencies.interface import *
from feat.interface.serialization import *
from feat.interface.task import *
from feat.interface.protocols import *


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

    implements(IAgencyTask, ISerializable, IListener)

    log_category = 'agency-task'

    type_name = 'task-medium'

    def __init__(self, agency_agent, factory, *args, **kwargs):
        log.Logger.__init__(self, agency_agent)
        log.LogProxy.__init__(self, agency_agent)
        common.StateMachineMixin.__init__(self)
        common.ExpirationCallsMixin.__init__(self)
        common.AgencyMiddleMixin.__init__(self)
        common.InitiatorMediumBase.__init__(self)

        self.agent = agency_agent
        self.factory = factory
        self.args = args
        self.kwargs = kwargs

    ### IAgencyTask Methods ###

    def initiate(self):
        self.agent.journal_protocol_created(self.factory, self,
                                            *self.args, **self.kwargs)
        task = self.factory(self.agent.get_agent(), self)
        # FIXME: Now that this is moved to the medium,
        # should we really register a listener for tasks ?
        self.agent.register_listener(self)

        self.task = task
        self.log_name = self.task.__class__.__name__

        self._set_state(TaskState.performing)

        self._cancel_expiration_call()
        timeout = self.agent.get_time() + self.task.timeout
        error = InitiatorExpired("Timeout exceeded waiting "
                                 "for task.initate()")
        self._expire_at(timeout, self._expired,
                TaskState.expired, failure.Failure(error))

        self.call_next(self._initiate, *self.args, **self.kwargs)

        return task

    def get_session_id(self):
        return self.session_id

    def get_agent_side(self):
        return self.task

    ### ISerializable Methods ###

    def snapshot(self):
        return id(self)

    ### Required by InitiatorMediumbase ###

    def call_next(self, _method, *args, **kwargs):
        return self.agent.call_next(_method, *args, **kwargs)

    # Used by ExpirationCallsMixin

    def _get_time(self):
        return self.agent.get_time()

    ### Private Methods ###

    def _initiate(self, *args, **kwargs):
        d = defer.maybeDeferred(self.task.initiate, *args, **kwargs)
        d.addCallbacks(self._completed, self._error)
        return d

    def _completed(self, arg):
        self._set_state(TaskState.completed)
        delay.callLater(0, self._terminate, arg)

    def _error(self, arg):
        self._set_state(TaskState.error)
        delay.callLater(0, self._terminate, arg)

    def _expired(self, arg):
        self._set_state(TaskState.expired)
        d = defer.maybeDeferred(self.task.expired)
        return d

    def _terminate(self, arg):
        common.ExpirationCallsMixin._terminate(self)

        self.log("Unregistering task %s" % self.session_id)
        self.agent.unregister_listener(self.session_id)

        common.InitiatorMediumBase._terminate(self, arg)


class AgencyTaskFactory(protocols.BaseInitiatorFactory):
    type_name = 'task-medium-factory'
    protocol_factory = AgencyTask

    def __call__(self, agency_agent, _recipients, *args, **kwargs):
        # Dropping recipients
        return self.protocol_factory(agency_agent, self._factory,
                                     *args, **kwargs)


components.registerAdapter(AgencyTaskFactory,
                           ITaskFactory,
                           IAgencyInitiatorFactory)
