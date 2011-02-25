# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from feat.agents.base import (agent, message, contractor, manager, recipient,
                              descriptor, replay, resource, partners)
from feat.agents.common import host
from feat.common import enum, fiber, serialization
from feat.interface.protocols import InterestType
from feat.interface.contracts import ContractState
from feat.agents.shard.contracts import ActionType


@serialization.register
class HostPartner(partners.BasePartner):

    type_name = 'shard->host'

    def initiate(self, agent):
        # Host Agent on the other end is about to join our shard,
        # his address will change.
        shard = agent.get_own_address().shard
        self.recipient = recipient.Agent(self.recipient.key, shard)

        if self.allocation_id is None:
            f = agent.allocate_resource(hosts=1)
            f.add_callback(self.set_allocation_id)
            return f

    def set_allocation_id(self, allocation):
        self.allocation_id = allocation.id


@serialization.register
class ParentShardPartner(partners.BasePartner):

    type_name = 'shard->parent'

    def initiate(self, agent):
        return agent.unbind_join_interest_from_lobby()

    def on_goodbye(self, agent):
        # TODO: NOT TESTED! It should be tested in failure recovery tests.
        return agent.start_join_shard_manager()


@serialization.register
class ChildShardPartner(partners.BasePartner):

    type_name = 'shard->child'

    def initiate(self, agent):
        if self.allocation_id is None:
            self.allocation_id = agent.preallocate_resource(children=1)
            return agent.confirm_allocation(self.allocation_id)


class Partners(partners.Partners):

    partners.has_many('hosts', 'host_agent', HostPartner)
    partners.has_many('children', 'shard_agent', ChildShardPartner, 'child')
    partners.has_one('parent', 'shard_agent', ParentShardPartner, 'parent')


@agent.register('shard_agent')
class ShardAgent(agent.BaseAgent):

    partners_class = Partners

    @replay.mutable
    def initiate(self, state, hosts=10, children=2):
        agent.BaseAgent.initiate(self)

        state.resources.define('hosts', hosts)
        state.resources.define('children', children)

        state.join_interest =\
            state.medium.register_interest(JoinShardContractor)
        state.join_interest.bind_to_lobby()
        return self.initiate_partners()

    @replay.journaled
    def start_join_shard_manager(self, state):
        if state.partners.parent is None:
            return start_join_shard_manager(state.medium, ActionType.adopt)

    @replay.journaled
    def prepare_child_descriptor(self, state):
        desc = Descriptor()

        def set_shard(desc):
            desc.shard = desc.doc_id
            return desc

        f = fiber.Fiber()
        f.add_callback(state.medium.save_document)
        f.add_callback(set_shard)
        f.add_callback(state.medium.save_document)
        f.succeed(desc)
        return f

    @replay.mutable
    def unbind_join_interest_from_lobby(self, state):
        state.join_interest.unbind_from_lobby()


@serialization.register
class JoinShardContractor(contractor.BaseContractor):

    protocol_id = 'join-shard'
    interest_type = InterestType.public

    @replay.mutable
    def announced(self, state, announcement):
        state.nested_manager = None
        our_action = None

        wants_join = ActionType.join in announcement.payload['solutions']
        wants_create = ActionType.create in announcement.payload['solutions']
        wants_adopt = ActionType.adopt in announcement.payload['solutions']

        if wants_join:
            allocation = state.agent.preallocate_resource(hosts=1)
            if allocation:
                our_action = ActionType.join
                cost = 0
        if our_action is None and (wants_adopt or wants_create):
            allocation = state.agent.preallocate_resource(children=1)
            if allocation:
                our_action = wants_create and ActionType.create or\
                                              ActionType.adopt
                cost = 20
        state.preallocation_id = allocation and allocation.id

        # create a bid for our own action
        bid = None
        if our_action is not None:
            bid = message.Bid()
            bid.payload['action_type'] = our_action
            cost += announcement.payload['level'] * 15
            bid.payload['cost'] = cost

        f = fiber.Fiber()
        if our_action in [ActionType.create, None]:
            # Maybe children shards can just join
            # this poor fellow, lets ask them.
            f.add_callback(fiber.drop_result, self._fetch_children_bids,
                           announcement)
        f.add_callback(self._pick_best_bid, bid)
        f.add_callback(self._bid_refuse_or_handover, bid)
        f.add_callback(fiber.drop_result, self._terminate_nested_manager)
        return f.succeed()

    @replay.mutable
    def _fetch_children_bids(self, state, announcement):
        children = state.agent.query_partners('children')
        if len(children) == 0:
            return list()

        new_announcement = announcement.clone()
        new_announcement.payload['level'] += 1

        state.nested_manager = state.agent.initiate_protocol(
            NestedJoinShardManager, children, new_announcement)
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
            f = fiber.Fiber()
            f.add_callback(self.release_preallocation)
            f.add_callback(fiber.drop_result, state.medium.handover, bid)
            return f.succeed()

    @replay.immutable
    def release_preallocation(self, state, *_):
        if state.preallocation_id is not None:
            return state.agent.release_resource(state.preallocation_id)

    announce_expired = release_preallocation
    rejected = release_preallocation
    expired = release_preallocation

    @replay.mutable
    def granted(self, state, grant):
        joining_agent_id = grant.payload['joining_agent'].key

        if state.bid.payload['action_type'] == ActionType.create:
            f = fiber.Fiber()
            f.add_callback(state.agent.confirm_allocation)
            f.add_callback(fiber.drop_result,
                           state.agent.prepare_child_descriptor)
            f.add_callback(self._request_start_agent)
            f.add_callback(self._extract_agent)
            f.add_callback(state.agent.establish_partnership,
                           state.preallocation_id, u'child', u'parent')
            f.add_callback(self._generate_new_address, joining_agent_id)
            f.add_callback(state.medium.update_manager_address)
            f.add_callbacks(self._finalize, self._granted_failed)
            return f.succeed(state.preallocation_id)
        elif state.bid.payload['action_type'] == ActionType.join:
            f = fiber.Fiber()
            f.add_callback(state.agent.confirm_allocation)
            f.add_callback(
                fiber.drop_result, state.agent.establish_partnership,
                grant.payload['joining_agent'], state.preallocation_id)
            f.add_callback(state.medium.update_manager_address)
            f.add_callbacks(self._finalize, self._granted_failed)
            return f.succeed(state.preallocation_id)
        elif state.bid.payload['action_type'] == ActionType.adopt:
            f = fiber.Fiber()
            f.add_callback(state.agent.confirm_allocation)
            f.add_callback(
                fiber.drop_result, state.agent.establish_partnership,
                grant.payload['joining_agent'], state.preallocation_id,
                u'child', u'parent')
            f.add_callbacks(self._finalize, self._granted_failed)
            return f.succeed(state.preallocation_id)

    def _granted_failed(self, failure):
        self.release_preallocation()
        failure.raiseException()

    @replay.immutable
    def _finalize(self, state, _):
        report = message.FinalReport()
        state.medium.finalize(report)

    @replay.immutable
    def _request_start_agent(self, state, desc):
        recp = state.medium.announce.payload['joining_agent']
        totals, _ = state.agent.list_resource()
        return host.start_agent(state.agent, recp, desc, **totals)

    def _extract_agent(self, reply):
        return reply.payload['agent']

    def _generate_new_address(self, shard_partner, agent_id):
        return recipient.Agent(agent_id, shard_partner.recipient.shard)


@serialization.register
class NestedJoinShardManager(manager.BaseManager):

    protocol_id = 'join-shard'

    @replay.journaled
    def initiate(self, state, announcement):
        state.medium.announce(announcement)

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


@descriptor.register("shard_agent")
class Descriptor(descriptor.Descriptor):
    pass
