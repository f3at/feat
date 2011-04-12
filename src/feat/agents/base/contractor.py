from zope.interface import implements

from feat.common import log, reflect, serialization, fiber
from feat.agents.base import message, replay, manager, recipient

from feat.interface.contractor import *
from feat.interface.contracts import *
from feat.interface.protocols import *


class Meta(type(replay.Replayable)):
    implements(IContractorFactory)

    def __init__(cls, name, bases, dct):
        cls.type_name = reflect.canonical_name(cls)
        serialization.register(cls)
        super(Meta, cls).__init__(name, bases, dct)


class BaseContractor(log.Logger, replay.Replayable):
    """
    I am a base class for contractors of contracts.

    @ivar protocol_type: the type of contract this contractor bids on.
                         Must match the type of the manager for this contract;
                         see L{feat.agents.manager.BaseManager}
    @type protocol_type: str
    """
    __metaclass__ = Meta

    implements(IAgentContractor)

    initiator = message.Announcement

    log_category = "contractor"
    protocol_type = "Contract"
    protocol_id = None
    interest_type = InterestType.private

    bid_timeout = 10
    ack_timeout = 10

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

    def announced(self, announcement):
        '''@see: L{contractor.IAgentContractor}'''

    def announce_expired(self):
        '''@see: L{contractor.IAgentContractor}'''

    def rejected(self, rejection):
        '''@see: L{contractor.IAgentContractor}'''

    def granted(self, grant):
        '''@see: L{contractor.IAgentContractor}'''

    def bid_expired(self):
        '''@see: L{contractor.IAgentContractor}'''

    def cancelled(self, grant):
        '''@see: L{contractor.IAgentContractor}'''

    def acknowledged(self, grant):
        '''@see: L{contractor.IAgentContractor}'''

    def aborted(self):
        '''@see: L{contractor.IAgentContractor}'''


class NestingContractor(BaseContractor):

    @replay.mutable
    def fetch_nested_bids(self, state, recipients, original_announcement):
        recipients = recipient.IRecipients(recipients)
        sender = original_announcement.reply_to
        if  sender in recipients:
            self.log("Removing sender from list of recipients to nest")
            recipients.remove(sender)
        if len(recipients) == 0:
            self.log("Empty list to nest to, will not nest")
            return list()
        else:
            self.log("Will nest contract to %d contractors.", len(recipients))

        announcement = original_announcement.clone()
        announcement.level += 1

        # nested contract needs to have a smaller window for gathering
        # bids, otherwise everything would expire
        current_time = state.agent.get_time()
        time_left = announcement.expiration_time - current_time
        expiration_time = current_time + 0.9 * time_left
        announcement.expiration_time = expiration_time

        state.nested_manager = state.agent.initiate_protocol(
            NestedManagerFactory(self.protocol_id, time_left),
            recipients, announcement)
        f = fiber.Fiber()
        f.add_callback(fiber.drop_result,
                       state.nested_manager.wait_for_bids)
        return f.succeed()

    @replay.immutable
    def terminate_nested_manager(self, state):
        if hasattr(state, 'nested_manager'):
            state.nested_manager.terminate()

    @replay.mutable
    def handover(self, state, bid):
        if hasattr(state, 'nested_manager'):
            state.nested_manager.elect(bid)
        state.medium.handover(bid)


@serialization.register
class NestedManagerFactory(serialization.Serializable):

    implements(manager.IManagerFactory)

    def __init__(self, protocol_id, time_left):
        self.time_left = time_left
        self.protocol_id = protocol_id

    def __call__(self, agent, medium, *args, **kwargs):
        instance = NestedManager(agent, medium, *args, **kwargs)
        instance.announce_timeout = self.time_left
        instance.protocol_id = self.protocol_id
        return instance

    def __repr__(self):
        return "<NestedManagerFactory for %r, time: %r>" %\
               (self.protocol_id, self.time_left, )

    def __eq__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return self.time_left == other.time_left and\
               self.protocol_id == other.protocol_id

    def __ne__(self, other):
        return not self.__eq__(other)


@serialization.register
class NestedManager(manager.BaseManager):

    @replay.journaled
    def initiate(self, state, announcement):
        state.medium.announce(announcement)

    @replay.immutable
    def wait_for_bids(self, state):
        f = fiber.succeed()
        f.add_callback(fiber.drop_result, state.medium.wait_for_state,
                       ContractState.closed, ContractState.expired)
        f.add_callback(fiber.drop_result, state.medium.get_bids)
        return f

    @replay.journaled
    def terminate(self, state):
        state.medium.terminate()

    @replay.immutable
    def elect(self, state, bid):
        state.medium.elect(bid)


@serialization.register
class Service(serialization.Serializable):
    implements(IContractorFactory)

    def __init__(self, factory):
        factory = IContractorFactory(factory)
        self.protocol_id = 'discover-' + factory.protocol_id
        self.protocol_type = factory.protocol_type
        self.initiator = factory.initiator
        self.interest_type = InterestType.public

    def __call__(self, agent, medium):
        instance = ServiceDiscoveryContractor(agent, medium)
        instance.protocol_id = self.protocol_id
        return instance

    def __eq__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return self.protocol_id == other.protocol_id and\
               self.protocol_type == other.protocol_type and\
               self.initiator == other.initiator and\
               self.interest_type == other.interest_type

    def __ne__(self, other):
        return not self.__eq__(other)


class ServiceDiscoveryContractor(BaseContractor):

    interest_type = InterestType.public

    @replay.journaled
    def announced(self, state, announcement):
        state.medium.bid(message.Bid())
