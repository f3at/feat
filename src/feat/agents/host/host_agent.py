# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from feat.agents.base import (agent, contractor, recipient, manager, message,
                              replay, replier, requester, descriptor,
                              partners, resource, )
from feat.interface.protocols import InterestType
from feat.common import fiber, manhole, serialization


@serialization.register
class ShardPartner(partners.BasePartner):

    type_name = 'host->shard'

    def initiate(self, agent):
        return agent.switch_shard(self.recipient.shard)

    def on_goodbye(self, agent):
        # TODO: NOT TESTED! Work in progress interupted by more important
        # task. Should be tested in the class:
        # f.t.i.test_simulation_tree_growth.FailureRecoverySimulation
        agent.info('Shard partner said goodbye. Trying to find new shard.')
        f = fiber.Fiber()
        f.add_callback(fiber.drop_result, self.start_join_shard_manager)
        return f.succeed()


class Partners(partners.Partners):

    partners.has_one('shard', 'shard_agent', ShardPartner)


@agent.register('host_agent')
class HostAgent(agent.BaseAgent):

    partners_class = Partners

    @replay.mutable
    def initiate(self, state, bootstrap=False):
        agent.BaseAgent.initiate(self)

        state.medium.register_interest(StartAgentReplier)
        state.medium.register_interest(ResourcesAllocationContractor)

        state.resources.define('host', 1)

        f = fiber.Fiber()
        f.add_callback(fiber.drop_result, self.initiate_partners)
        if not bootstrap:
            f.add_callback(fiber.drop_result, self.start_join_shard_manager)
        return f.succeed()

    @replay.journaled
    def start_join_shard_manager(self, state):
        if state.partners.shard is None:
            recp = recipient.Agent('join-shard', 'lobby')
            retrier = state.medium.retrying_protocol(JoinShardManager, recp)

            f = fiber.Fiber()
            f.add_callback(fiber.drop_result, retrier.notify_finish)
            return f.succeed()

    @replay.journaled
    def switch_shard(self, state, shard):
        self.debug('Switching shard to %r', shard)
        desc = state.medium.get_descriptor()

        def save_change(desc, shard):
            desc.shard = shard

        f = fiber.Fiber()
        f.add_callback(fiber.drop_result, state.medium.leave_shard, desc.shard)
        f.add_callback(fiber.drop_result, self.update_descriptor,
                       save_change, shard)
        f.add_callback(fiber.drop_result, state.medium.join_shard, shard)
        return f.succeed()

    @manhole.expose()
    @replay.journaled
    def start_agent(self, state, doc_id, *args, **kwargs):
        if isinstance(doc_id, descriptor.Descriptor):
            doc_id = doc_id.doc_id
        assert isinstance(doc_id, (str, unicode, ))
        f = fiber.Fiber()
        f.add_callback(self.get_document)
        f.add_callback(self._update_shard_field)
        f.add_callback(state.medium.start_agent, *args, **kwargs)
        f.add_callback(recipient.IRecipient)
        f.add_callback(self.establish_partnership, our_role=u'host')
        f.succeed(doc_id)
        return f

    @manhole.expose()
    @replay.journaled
    def start_agent_from_descriptor(self, state, desc):
        return self.start_agent(desc.doc_id)

    @replay.immutable
    def _update_shard_field(self, state, desc):
        '''Sometime creating the descriptor for new agent we cannot know in
        which shard it will endup. If it is None or set to lobby, the HA
        will update the field to match his own'''
        if desc.shard is None or desc.shard == 'lobby':
            desc.shard = self.get_own_address().shard
        f = fiber.Fiber()
        f.add_callback(state.medium.save_document)
        return f.succeed(desc)


class StartAgentRequester(requester.BaseRequester):

    protocol_id = 'start-agent'
    timeout = 10

    def init_state(self, state, agent, medium, descriptor, *args, **kwargs):
        requester.BaseRequester.init_state(self, state, agent, medium)
        state.descriptor = descriptor
        state.args = args
        state.kwargs = kwargs

    @replay.mutable
    def initiate(self, state):
        msg = message.RequestMessage()
        msg.payload['doc_id'] = state.descriptor.doc_id
        msg.payload['args'] = state.args
        msg.payload['kwargs'] = state.kwargs
        state.medium.request(msg)

    def got_reply(self, reply):
        return reply


class StartAgentReplier(replier.BaseReplier):

    protocol_id = 'start-agent'

    @replay.entry_point
    def requested(self, state, request):
        f = fiber.Fiber()
        f.add_callbacks(state.agent.start_agent,
                        cbargs=request.payload['args'],
                        cbkws=request.payload['kwargs'])
        f.add_callback(self._send_reply)
        f.succeed(request.payload['doc_id'])
        return f

    @replay.mutable
    def _send_reply(self, state, new_agent):
        msg = message.ResponseMessage()
        msg.payload['agent'] = recipient.IRecipient(new_agent)
        state.medium.reply(msg)


class JoinShardManager(manager.BaseManager):

    protocol_id = 'join-shard'

    @replay.immutable
    def initiate(self, state):
        msg = message.Announcement()
        msg.payload['level'] = 0
        msg.payload['joining_agent'] = state.agent.get_own_address()
        state.medium.announce(msg)

    @replay.immutable
    def closed(self, state):
        bids = state.medium.get_bids()
        best_bid = message.Bid.pick_best(bids)
        msg = message.Grant()
        msg.payload['joining_agent'] = state.agent.get_own_address()
        params = (best_bid, msg)
        state.medium.grant(params)

    @replay.mutable
    def completed(self, state, reports):
        pass


class ResourcesAllocationContractor(contractor.BaseContractor):
    protocol_id = 'allocate-resources'
    interest_type = InterestType.public

    @replay.mutable
    def announced(self, state, announcement):
        resources = announcement.payload['resources']
        try:
            preallocation = state.agent.preallocate_resource(**resources)
        except resource.UnknownResource:
            self._refuse("Unknown resource! WTF?")
            return

        if preallocation is None:
            self._refuse("Not enough resource")
            return

        state.preallocation_id = preallocation.id
        # Create a bid
        bid = message.Bid()
        bid.payload['allocation_id'] = state.preallocation_id

        f = fiber.Fiber()
        f.add_callback(self._get_cost)
        f.add_callback(state.medium.bid)
        return f.succeed(bid)

    @replay.immutable
    def _refuse(self, state, reason):
        state.medium.refuse(message.Refusal(payload=reason))

    @replay.immutable
    def _get_cost(self, state, bid):
        bid.payload['cost'] = 0
        return bid

    @replay.mutable
    def release_preallocation(self, state, *_):
        if state.preallocation_id is not None:
            return state.agent.release_resource(state.preallocation_id)

    announce_expired = release_preallocation
    rejected = release_preallocation
    expired = release_preallocation

    @replay.mutable
    def granted(self, state, grant):
        f = fiber.Fiber()
        f.add_callback(state.agent.confirm_allocation)
        f.add_callback(self._finalize)
        return f.succeed(state.preallocation_id)

    @replay.mutable
    def _finalize(self, state, allocation_id):
        report = message.FinalReport()
        report.payload['allocation_id'] = allocation_id
        state.medium.finalize(report)


@descriptor.register("host_agent")
class Descriptor(descriptor.Descriptor):
    pass
