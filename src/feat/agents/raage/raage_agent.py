# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from feat.agents.base import agent, contractor, descriptor
from feat.agents.base import manager, message, recipient, replay
from feat.common import fiber
from feat.interface.contracts import ContractState
from feat.interface.protocols import InterestType


@agent.register('raage_agent')
class ResourcesAllocationAgent(agent.BaseAgent):

    @replay.mutable
    def initiate(self, state):
        agent.BaseAgent.initiate(self)
        state.medium.register_interest(AllocationContractor)


class AllocationContractor(contractor.BaseContractor):
    protocol_id = 'request-allocation'
    interest_type = InterestType.public

    @replay.mutable
    def announced(self, state, announcement):

        f = fiber.Fiber()
        f.add_callback(fiber.drop_result,
                       self._fetch_allocations, announcement)
        f.add_callback(self._pick_best_bid)
        f.add_callback(self._refuse_or_handover)
        f.add_callback(fiber.drop_result, self._terminate_nested_manager)
        return f.succeed()

    @replay.mutable
    def _fetch_allocations(self, state, announcement):
        shard = state.agent.get_own_address().shard
        recp = recipient.Broadcast('allocate-resources', shard)

        state.nested_manager = state.agent.initiate_protocol(
            NestedAllocationManager, recp, announcement.clone())

        f = fiber.Fiber()
        f.add_callback(fiber.drop_result, state.nested_manager.wait_for_bids)
        return f.succeed()

    @replay.immutable
    def _terminate_nested_manager(self, state):
        if state.nested_manager:
            state.nested_manager.terminate()

    @replay.immutable
    def _pick_best_bid(self, state, bids):
        if bids is None:
            return
        return message.Bid.pick_best(bids)

    @replay.journaled
    def _refuse_or_handover(self, state, bid):
        if bid is None:
            refusal = message.Refusal()
            return state.medium.refuse(refusal)
        else:
            state.nested_manager.elect(bid)
            return state.medium.handover(bid)


class NestedAllocationManager(manager.BaseManager):
    '''
    Send contracts to host agents in the shard, requesting for resources
    allocation
    '''

    protocol_id = 'allocate-resources'
    announce_timeout = 5

    @replay.mutable
    def initiate(self, state, announcement):
        '''
        @payload resources: list of resources to allocate
        '''
        state.announcement = announcement
        state.medium.announce(state.announcement)

    @replay.immutable
    def wait_for_bids(self, state):
        f = fiber.Fiber()
        f.add_callback(state.medium.wait_for_state)
        f.add_callback(lambda _: state.medium.get_bids())
        f.succeed(ContractState.closed)
        return f

    @replay.immutable
    def elect(self, state, bid):
        state.medium.elect(bid)

    @replay.journaled
    def terminate(self, state):
        state.medium.terminate()


@descriptor.register("raage_agent")
class Descriptor(descriptor.Descriptor):
    pass
