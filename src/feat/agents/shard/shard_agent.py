# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from feat.agents.base import (agent, message, contractor, manager, recipient,
                              descriptor, document, replay)
from feat.common import enum, fiber, serialization
from feat.interface.protocols import InterestType
from feat.interface.contracts import ContractState
from feat.agents.host import host_agent


@agent.register('shard_agent')
class ShardAgent(agent.BaseAgent):

    @replay.mutable
    def initiate(self, state):
        agent.BaseAgent.initiate(self)

        state.resources.define('hosts', 10)
        state.resources.define('children', 2)

        desc = state.medium.get_descriptor()
        assert(isinstance(desc, Descriptor))
        for x in range(len(desc.children)):
            state.resources.allocate(children=1)
        for x in range(len(desc.hosts)):
            state.resources.allocate(hosts=1)

        interest = state.medium.register_interest(JoinShardContractor)
        if desc.parent is None:
            interest.bind_to_lobby()

    @agent.update_descriptor
    def add_children_shard(self, state, descriptor, child):
        descriptor.children.append(child)
        return child

    @agent.update_descriptor
    def add_agent(self, state, descriptor, agent_id):
        recp = recipient.Agent(agent_id, descriptor.shard)
        descriptor.hosts.append(recp)
        return recp

    @replay.journaled
    def prepare_child_descriptor(self, state, joining_host_id=None):
        us = self.get_own_address()
        desc = Descriptor(parent=us)

        def set_shard(desc):
            desc.shard = desc.doc_id
            return desc

        def append_child(desc, joining_host_id):
            new_address = recipient.Agent(joining_host_id, desc.shard)
            desc.hosts.append(new_address)
            return desc

        f = fiber.Fiber()
        f.add_callback(state.medium.save_document)
        f.add_callback(set_shard)
        if joining_host_id is not None:
            f.add_callback(append_child, joining_host_id)
        f.add_callback(state.medium.save_document)
        f.succeed(desc)
        return f


@serialization.register
class JoinShardContractor(contractor.BaseContractor):

    protocol_id = 'join-shard'
    interest_type = InterestType.public

    @replay.mutable
    def announced(self, state, announcement):
        state.preallocation = state.agent.preallocate_resource(hosts=1)
        state.nested_manager = None
        action_type = None

        # check if we can serve the request on our own
        if state.preallocation:
            action_type = ActionType.join
            cost = 0
        else:
            state.preallocation = state.agent.preallocate_resource(children=1)
            if state.preallocation:
                action_type = ActionType.create
                cost = 20

        # create a bid for our own action
        bid = None
        if action_type is not None:
            bid = message.Bid()
            bid.payload['action_type'] = action_type
            cost += announcement.payload['level'] * 15
            bid.payload['cost'] = cost

        f = fiber.Fiber()
        if action_type != ActionType.join:
            f.add_callback(fiber.drop_result, self._fetch_children_bids,
                           announcement)
        f.add_callback(self._pick_best_bid, bid)
        f.add_callback(self._bid_refuse_or_handover, bid)
        f.add_callback(fiber.drop_result, self._terminate_nested_manager)
        return f.succeed()

    @replay.mutable
    def _fetch_children_bids(self, state, announcement):
        desc = state.agent.get_descriptor()
        if len(desc.children) == 0:
            return list()

        new_announcement = announcement.clone()
        new_announcement.payload['level'] += 1

        state.nested_manager = state.agent.initiate_protocol(
            NestedJoinShardManager, desc.children, new_announcement)
        f = fiber.Fiber()
        f.add_callback(fiber.drop_result,
                       state.nested_manager.wait_for_bids)
        return f.succeed()

    @replay.immutable
    def _terminate_nested_manager(self, state):
        if state.nested_manager:
            state.nested_manager.terminate()

    @replay.immutable
    def _pick_best_bid(self, state, nested_bids, own_bid):
        # prepare the list of bids
        bids = list()
        if own_bid:
            bids.append(own_bid)
        if nested_bids is None:
            nested_bids = list()
        bids += nested_bids
        self.log('_pick_best_bid analizes total of %d bids', len(bids))

        # check if we have received anything
        if len(bids) == 0:
            self.info('Did not receive any bids to evaluate! '
                      'Contract will fail.')
            return None

        # elect best bid
        best = message.Bid.pick_best(bids)

        # Send refusals to contractors of nested manager which we already
        # know will not receive the grant.
        for bid in bids:
            if bid == best:
                continue
            elif bid in nested_bids:
                state.nested_manager.reject_bid(bid)
        return best

    @replay.journaled
    def _bid_refuse_or_handover(self, state, bid=None, original_bid=None):
        if bid is None:
            refusal = message.Refusal()
            return state.medium.refuse(refusal)
        elif bid == original_bid:
            state.bid = bid
            return state.medium.bid(bid)
        else:
            self.release_preallocation()
            return state.medium.handover(bid)

    @replay.mutable
    def release_preallocation(self, state, *_):
        if state.preallocation is not None:
            state.preallocation.release()

    announce_expired = release_preallocation
    rejected = release_preallocation
    expired = release_preallocation

    @replay.mutable
    def granted(self, state, grant):
        state.preallocation.confirm()

        joining_agent_id = grant.payload['joining_agent'].key

        if state.bid.payload['action_type'] == ActionType.create:
            f = fiber.Fiber()
            f.add_callback(state.agent.prepare_child_descriptor)
            f.add_callback(self._request_start_agent)
            f.add_callback(self._extract_agent)
            f.add_callback(state.agent.add_children_shard)
            f.add_callback(self._finalize)
            f.succeed(joining_agent_id)
            return f
        else: # ActionType.join
            f = fiber.Fiber()
            f.add_callback(state.agent.add_agent)
            f.add_callback(self._finalize)
            f.succeed(joining_agent_id)
            return f

    @replay.immutable
    def _finalize(self, state, recp):
        report = message.FinalReport()
        report.payload['shard'] = recp.shard
        state.medium.finalize(report)

    @replay.immutable
    def _request_start_agent(self, state, desc):
        recp = state.medium.announce.payload['joining_agent']
        f = fiber.Fiber()
        f.add_callback(state.agent.initiate_protocol, recp, desc)
        f.add_callback(host_agent.StartAgentRequester.notify_finish)
        f.succeed(host_agent.StartAgentRequester)
        return f

    def _extract_agent(self, reply):
        return reply.payload['agent']


@serialization.register
class NestedJoinShardManager(manager.BaseManager):

    protocol_id = 'join-shard'

    def init_state(self, state, agent, medium, announcement):
        manager.BaseManager.init_state(self, state, agent, medium)
        state._announcement = announcement

    @replay.journaled
    def initiate(self, state):
        state.medium.announce(state._announcement)

    @replay.immutable
    def wait_for_bids(self, state):
        f = fiber.Fiber()
        f.add_callback(state.medium.wait_for_state)
        f.add_callback(lambda _: state.medium.contractors.keys())
        f.succeed(ContractState.closed)
        return f

    @replay.journaled
    def reject_bid(self, state, bid):
        self.debug('Sending rejection to bid from nested manager.')
        return state.medium.reject(bid)

    @replay.journaled
    def terminate(self, state):
        state.medium.terminate()


class ActionType(enum.Enum):
    '''
    The type solution we are offering:

    join   - join the existing shard
    create - start your own ShardAgent as a child bid sender
    '''
    (join, create) = range(2)


@document.register
class Descriptor(descriptor.Descriptor):

    document_type = 'shard_agent'
    document.field('parent', None)
    document.field('hosts', list())
    document.field('children', list())
