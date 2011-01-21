# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from feat.agents.base import (agent, recipient, manager, message, replay,
                              replier, requester, document, descriptor,
                              partners)
from feat.common import fiber, serialization


@serialization.register
class ShardPartner(partners.BasePartner):

    type_name = 'host->shard'

    def initiate(self, agent):
        return agent.switch_shard(self.recipient.shard)


class Partners(partners.Partners):

    partners.has_one('shard_a', 'shard_agent', ShardPartner)


@agent.register('host_agent')
class HostAgent(agent.BaseAgent):

    partners_class = Partners

    @replay.mutable
    def initiate(self, state):
        agent.BaseAgent.initiate(self)

        state.medium.register_interest(StartAgentReplier)

        f = fiber.Fiber()
        f.add_callback(fiber.drop_result, self.initiate_partners)
        f.add_callback(fiber.drop_result, self.start_join_shard_manager)
        return f.succeed()

    @replay.journaled
    def start_join_shard_manager(self, state):
        if state.partners.shard_a is None:
            recp = recipient.Agent('join-shard', 'lobby')
            retrier = state.medium.retrying_protocol(JoinShardManager, recp)

            f = fiber.Fiber()
            f.add_callback(fiber.drop_result, retrier.notify_finish)
            return f.succeed()

    @agent.update_descriptor
    def switch_shard(self, state, desc, shard):
        self.debug('Switching shard to %r', shard)
        state.medium.leave_shard(desc.shard)
        desc.shard = shard
        state.medium.join_shard(shard)

    @replay.immutable
    def start_agent(self, state, doc_id):
        f = fiber.Fiber()
        f.add_callback(self.get_document)
        f.add_callback(self._update_host_field)
        f.add_callback(state.medium.start_agent)
        f.add_callback(recipient.IRecipient)
        f.add_callback(self.establish_partnership)
        f.succeed(doc_id)
        return f

    @replay.immutable
    def _update_host_field(self, state, desc):
        desc.host = self.get_own_address()
        f = fiber.Fiber()
        f.add_callback(state.medium.save_document)
        return f.succeed(desc)


class StartAgentRequester(requester.BaseRequester):

    protocol_id = 'start-agent'
    timeout = 10

    def init_state(self, state, agent, medium, descriptor):
        requester.BaseRequester.init_state(self, state, agent, medium)
        state.descriptor = descriptor

    @replay.mutable
    def initiate(self, state):
        msg = message.RequestMessage()
        msg.payload['doc_id'] = state.descriptor.doc_id
        state.medium.request(msg)

    def got_reply(self, reply):
        return reply


class StartAgentReplier(replier.BaseReplier):

    protocol_id = 'start-agent'

    @replay.entry_point
    def requested(self, state, request):
        f = fiber.Fiber()
        f.add_callback(state.agent.start_agent)
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


@document.register
class Descriptor(descriptor.Descriptor):

    document_type = 'host_agent'
