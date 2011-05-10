from zope.interface import implements, classProvides

from feat.agencies import common
from feat.common import log, defer, time
from feat.common import serialization, error_handler

from feat.agencies.interface import *
from feat.interface.serialization import *
from feat.interface.protocols import *

DEFAULT_PERIOD = 10


@serialization.register
class PeriodicProtocolFactory(serialization.Serializable):

    implements(IInitiatorFactory, IAgencyInitiatorFactory)

    type_name="periodic-protocol-factory"

    protocol_type = "Special"

    def __init__(self, factory, period=None, busy=False):
        self.protocol_id = "periodic-" + factory.protocol_id
        self.factory = factory
        self.period = period
        self.busy = busy

    def __call__(self, agency_agent, *args, **kwargs):
        return PeriodicProtocol(agency_agent, self.factory,
                                args, kwargs,
                                period=self.period,
                                busy=self.busy)

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return (self.__dict__ == other.__dict__)

    def __ne__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return (self.__dict__ != other.__dict__)


class PeriodicProtocol(common.InitiatorMediumBase, log.Logger):

    classProvides(IInitiatorFactory)
    implements(ISerializable, ILongRunningProtocol)

    log_category="periodic-protocol"

    type_name="periodic-protocol"

    protocol_type = "Special"

    def __init__(self, agency_agent, factory,
                 args=None, kwargs=None, period=None, busy=False):
        common.InitiatorMediumBase.__init__(self)
        log.Logger.__init__(self, agency_agent)

        self.protocol_id = "periodic-" + factory.protocol_id

        self.medium = agency_agent
        self.factory = factory
        self.args = args or ()
        self.kwargs = kwargs or {}

        self.period = period or DEFAULT_PERIOD
        self.busy = busy

        self._delayed_call = None
        self._initiator = None
        self._canceled = False
        self._notifier = defer.Notifier()

    def initiate(self):
        self.call_next(self._start_protocol)
        return self

    ### Public Methods ###

    def call_next(self, _method, *args, **kwargs):
        return self.medium.call_next(_method, *args, **kwargs)

    ### ILongRunningProtocol Methods ###

    @serialization.freeze_tag('PeriodicProtocol.cancel')
    def cancel(self):
        self._canceled = True
        self._cancel_protocol()
        self._notifier.callback("finished", self)
        return defer.succeed(self)

    def is_idle(self):
        if self._initiator is not None:
            return self._initiator.is_idle()
        return not self.busy

    @serialization.freeze_tag('PeriodicProtocol.notify_finish')
    def notify_finish(self):
        if self._canceled:
            return defer.succeed(self)
        return self._notifier.wait("finised")

    ### ISerializable Methods ###

    def snapshot(self):
        return id(self)

    ### Private Methods ###

    def _cancel_protocol(self):
        if self._delayed_call:
            if self._delayed_call.active():
                self._delayed_call.cancel()
            self._delayed_call = None

    def _start_protocol(self):
        self._cancel_protocol()
        ini = self.medium.initiate_protocol(self.factory,
                                            *self.args, **self.kwargs)
        d = ini.notify_finish()
        d.addCallback(self._schedule_protocol)
        d.addErrback(defer.inject_param, 1, error_handler, self)
        return d

    def _schedule_protocol(self, _):
        self._delayed_call = time.callLater(self.period, self._start_protocol)
