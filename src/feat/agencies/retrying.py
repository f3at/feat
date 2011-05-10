from twisted.python.failure import Failure
from zope.interface import implements

from feat.agencies import common
from feat.common import log, defer, serialization

from feat.agencies.interface import *
from feat.interface.serialization import *
from feat.interface.protocols import *


@serialization.register
class RetryingProtocolFactory(serialization.Serializable):

    implements(IInitiatorFactory, IAgencyInitiatorFactory)

    type_name="retrying-protocol-factory"

    protocol_type = "Special"

    def __init__(self, factory, max_retries=None,
                 initial_delay=1, max_delay=None, busy=True):
        self.protocol_id = "retried-" + factory.protocol_id
        self.factory = factory
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.busy = busy

    def __call__(self, agency_agent, *args, **kwargs):
        return RetryingProtocol(agency_agent, self.factory,
                                args, kwargs,
                                max_retries=self.max_retries,
                                initial_delay=self.initial_delay,
                                max_delay=self.max_delay,
                                busy=self.busy)

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return (self.__dict__ == other.__dict__)

    def __ne__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return (self.__dict__ != other.__dict__)


class RetryingProtocol(common.TransientInitiatorMediumBase, log.Logger):

    implements(ISerializable, ILongRunningProtocol)

    log_category="retrying-protocol"

    type_name="retrying-protocol"

    protocol_type = "Special"

    def __init__(self, agency_agent, factory, args=None, kwargs=None,
                 max_retries=None, initial_delay=1, max_delay=None, busy=True):
        common.TransientInitiatorMediumBase.__init__(self)
        log.Logger.__init__(self, agency_agent)

        self.protocol_id = "retried-" + factory.protocol_id

        self.medium = agency_agent
        self.factory = factory
        self.args = args or ()
        self.kwargs = kwargs or {}

        self.max_retries = max_retries
        self.max_delay = max_delay
        self.attempt = 0
        self.delay = initial_delay
        self.busy = busy # If the protocol should not be idle between retries

        self._delayed_call = None
        self._initiator = None

    ### Public Methods ###

    def initiate(self):
        self.call_next(self._bind)
        return self

    @serialization.freeze_tag('RetryingProtocol.notify_finish')
    def notify_finish(self):
        return common.TransientInitiatorMediumBase.notify_finish(self)

    def call_later(self, _time, _method, *args, **kwargs):
        return self.medium.call_later(_time, _method, *args, **kwargs)

    ### ILongRunningProtocol Methods ###

    @serialization.freeze_tag('RetryingProtocol.cancel')
    def cancel(self):
        self.max_retries = self.attempt - 1
        if self._delayed_call:
            self.medium.cancel_delayed_call(self._delayed_call)
            self._delayed_call = None
            return defer.succeed(None)
        if self._initiator:
            #FIXME: we shouldn't have to use _get_state()
            d = self._initiator._get_state().medium.expire_now()
            d.addErrback(Failure.trap, ProtocolFailed)
            return d

    def is_idle(self):
        if self._initiator is not None:
            return self._initiator.is_idle()
        return not self.busy

    ### ISerializable Methods ###

    def snapshot(self):
        return id(self)

    ### Required by TransientInitiatorMediumbase ###

    def call_next(self, _method, *args, **kwargs):
        return self.medium.call_next(_method, *args, **kwargs)

    ### Private Methods ###

    def _bind(self):
        d = self._fire()
        d.addCallbacks(self._finalize, self._wait_and_retry)

    def _fire(self):
        self.attempt += 1
        self._initiator = self.medium.initiate_protocol(self.factory,
                                                        *self.args,
                                                        **self.kwargs)
        d = self._initiator.notify_finish()
        return d

    def _finalize(self, result):
        common.TransientInitiatorMediumBase._terminate(self, result)

    def _wait_and_retry(self, failure):
        self.info('Retrying failed for the %d time with %s %s factory %r',
                  self.attempt, self.medium.agent.descriptor_type,
                  self.medium.get_full_id(), self.factory)

        self._initiator = None

        # check if we are done
        if self.max_retries is not None and self.attempt > self.max_retries:
            self.info("Will not try to restart.")
            common.TransientInitiatorMediumBase._terminate(self, failure)
            return

        # do retry
        self.info('Will retry in %d seconds', self.delay)
        self._delayed_call = self.call_later(self.delay, self._bind)

        # adjust the delay
        if self.max_delay is None:
            self.delay *= 2
        elif self.delay < self.max_delay:
            self.delay = min((2 * self.delay, self.max_delay, ))
