import uuid

from twisted.python import components
from zope.interface import implements, classProvides

from feat.agencies import common
from feat.agents.base import replay
from feat.common import log, defer, time
from feat.common import container, serialization, error_handler

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

    agency_agent = None
    agent_factory = None

    binding = None

    def __init__(self, agent_factory, *args, **kwargs):
        self.agent_factory = agent_factory
        self.args = args
        self.kwargs = kwargs

        self._lobby_binding = None
        self._concurrency = getattr(agent_factory, "concurrency", None)
        self._queue = None
        self._active = 0
        self._notifier = defer.Notifier()

    ### Public Methods ###

    def __eq__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return (self.agent_factory == other.agent_factory
                and self.args == other.args
                and self.kwargs == other.kwargs)

    def __ne__(self, other):
        eq = self.__eq__(other)
        return eq if eq is NotImplemented else not eq

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
        The counter is decreased in synchronous method just before popping
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

    def schedule_message(self, message):
        if not isinstance(message, self.agent_factory.initiator):
            return False

        if self._queue is not None:
            if self._active >= self._concurrency:
                self.debug('Scheduling %s protocol %s',
                           message.protocol_type, message.protocol_id)
                self._queue.add(message, message.expiration_time)
                return True

        self._process_message(message)

        return True

    def bind(self, shard=None):
        if self.agent_factory.interest_type == InterestType.public:
            prot_id = self.agent_factory.protocol_id
            self.binding = self.agency_agent.create_binding(prot_id, shard)
            return self.binding

    def revoke(self):
        self.clear_queue()
        self.unbind_from_lobby()
        if self.agent_factory.interest_type == InterestType.public:
            self.binding.revoke()

    ### IAgencyInterest Method ###

    @replay.named_side_effect('Interest.bind_to_lobby')
    def bind_to_lobby(self):
        if self._lobby_binding is not None:
            return
        prot_id = self.agent_factory.protocol_id
        binding = self.agency_agent.create_binding(prot_id, 'lobby')
        self._lobby_binding = binding

    @replay.named_side_effect('Interest.unbind_from_lobby')
    def unbind_from_lobby(self):
        if self._lobby_binding is None:
            return
        self._lobby_binding.revoke()
        self._lobby_binding = None

    ### ISerializable Methods ###

    def snapshot(self):
        return self.agent_factory, self.args, self.kwargs

    ### Protected Methods ###

    def _process_message(self, message):
        assert not self._concurrency or self._active < self._concurrency
        self._active += 1

    def _message_processed(self, message):
        self.debug('Message %s for protocol %s processed',
                   message.protocol_type, message.protocol_id)
        assert self._active > 0
        self._active -= 1
        if self._queue is not None:
            try:
                message = self._queue.pop()
                self._process_message(message)
                return
            except container.Empty:
                pass
        if self._active == 0:
            # All protocols terminated and empty queue
            self._notifier.callback("finished", self)


class DialogInterest(BaseInterest):

    def _process_message(self, message):
        BaseInterest._process_message(self, message)

        self.debug('Instantiating %s protocol %s',
                   message.protocol_type, message.protocol_id)

        medium_factory = IAgencyInterestedFactory(self.agent_factory)
        medium = medium_factory(self.agency_agent, message,
                                *self.args, **self.kwargs)
        medium.initiate()
        protocol = self.agency_agent.register_protocol(medium)
        medium.notify_finish().addBoth(defer.drop_param,
                                       self._message_processed, message)

        self.agency_agent.call_next(protocol.on_message, message)
