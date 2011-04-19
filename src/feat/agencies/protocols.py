from zope.interface import implements

from feat.common import log, serialization, defer, container
from feat.agents.base import replay

from feat.agencies.interface import *
from feat.interface.serialization import *
from feat.interface.protocols import *


class BaseInitiatorFactory(object):

    implements(IAgencyInitiatorFactory, ISerializable)

    protocol_factory = None

    def __init__(self, factory):
        self._factory = factory

    ### IAgencyInitiatorFactory Methods ###

    def __call__(self, agency_agent, recipients, *args, **kwargs):
        return self.protocol_factory(agency_agent, self._factory,
                                     recipients, *args, **kwargs)

    ### ISerializable Methods ###

    def snapshot(self):
        return None


class BaseInterestedFactory(object):

    implements(IAgencyInterestedFactory, ISerializable)

    protocol_factory = None

    def __init__(self, factory):
        self._factory = factory

    ### IAgencyInterestedFactory Methods ###

    def __call__(self, agency_agent, message):
        return self.protocol_factory(agency_agent, self._factory, message)

    ### ISerializable Methods ###

    def snapshot(self):
        return None


class BaseInterest(log.Logger):
    '''Represents the interest from the point of view of agency.
    Manages the binding and stores factory reference'''

    implements(IAgencyInterestInternalFactory, IAgencyInterestInternal,
               IAgencyInterest, ISerializable)

    type_name = "agent-interest"
    log_category = "agent-interest"

    factory = None
    binding = None

    def __init__(self, factory):
        self.factory = factory
        self.agency_agent = None
        self._lobby_binding = None
        self._concurrency = getattr(factory, "concurrency", None)
        self._queue = None
        self._active = 0
        self._notifier = defer.Notifier()

    ### Public Methods ###

    def __eq__(self, other):
        return self.factory == other.factory

    def __ne__(self, other):
        return not self.__eq__(other)

    ### IAgencyInterestInternalFactory Methods ###

    def __call__(self, agency_agent):
        log.Logger.__init__(self, agency_agent)

        self.agency_agent = agency_agent

        if self._concurrency is not None:
            self._queue = container.ExpQueue(agency_agent)

        self.bind()

        return self

    ### IAgencyInterestInternal Methods ###

    def is_idle(self):
        '''
        If self._active == 0 it means that the queue is empty.
        The counter is decreased in synchronous method just before poping
        the next value from the queue.
        '''
        return self._active == 0

    def wait_finished(self):
        if self.is_idle():
            return defer.succeed(self)
        return self._notifier.wait("finished")

    def clear_queue(self):
        if self._queue is not None:
            self._queue.clear()

    def schedule_protocol(self, message):
        if not isinstance(message, self.factory.initiator):
            return False

        if self._queue is not None:
            if self._active >= self._concurrency:
                self.debug('Scheduling %s protocol %s',
                           message.protocol_type, message.protocol_id)
                self._queue.add(message, message.expiration_time)
                return True

        self._initiate_protocol(message)

        return True

    def bind(self, shard=None):
        if self.factory.interest_type == InterestType.public:
            prot_id = self.factory.protocol_id
            self.binding = self.agency_agent.create_binding(prot_id, shard)
            return self.binding

    def revoke(self):
        if self.factory.interest_type == InterestType.public:
            self.binding.revoke()

    ### IAgencyInterest Method ###

    @replay.named_side_effect('Interest.bind_to_lobby')
    def bind_to_lobby(self):
        assert self._lobby_binding is None
        prot_id = self.factory.protocol_id
        binding = self.agency_agent._messaging.personal_binding(prot_id,
                                                                'lobby')
        self._lobby_binding = binding

    @replay.named_side_effect('Interest.unbind_from_lobby')
    def unbind_from_lobby(self):
        self._lobby_binding.revoke()
        self._lobby_binding = None

    ### ISerializable Methods ###

    def snapshot(self):
        return self.factory

    ### Private Methods ###

    def _initiate_protocol(self, message):
        self.debug('Instantiating %s protocol %s',
                   message.protocol_type, message.protocol_id)
        assert not self._concurrency or self._active < self._concurrency
        self._active += 1

        medium_factory = IAgencyInterestedFactory(self.factory)
        medium = medium_factory(self.agency_agent, message)
        protocol = medium.initiate()
        listener = self.agency_agent.register_listener(medium)
        medium.notify_finish().addBoth(defer.drop_result,
                                       self._protocol_terminated,
                                       message, protocol)

        self.agency_agent.call_next(listener.on_message, message)

    def _protocol_terminated(self, message, _protocol):
        self.debug('%s protocol %s terminated',
                   message.protocol_type, message.protocol_id)
        assert self._active > 0
        self._active -= 1
        if self._queue is not None:
            try:
                message = self._queue.pop()
                self._initiate_protocol(message)
                return
            except container.Empty:
                pass
        if self._active == 0:
            # All protocols terminated and empty queue
            self._notifier.callback("finished", self)


class DialogInterest(BaseInterest):
    pass
