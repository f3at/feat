# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from feat.agents.base import (agent, recipient, manager, message, replay,
                              replier, requester, document, descriptor, )
from feat.common import fiber, serialization
from feat.agencies import agency


@agent.register('host_agent')
class HostAgent(agent.BaseAgent):

    @replay.mutable
    def initiate(self, state):
        agent.BaseAgent.initiate(self)

        state.medium.register_interest(StartAgentReplier)

        recp = recipient.Agent('join-shard', 'lobby')
        join_manager = state.medium.initiate_protocol(JoinShardManager, recp)
        f = fiber.Fiber()
        f.add_callback(fiber.drop_result, join_manager.notify_finish)
        return f.succeed()

    @agent.update_descriptor
    def switch_shard(self, state, desc, shard):
        state.medium.leave_shard(desc.shard)
        desc.shard = shard
        state.medium.join_shard(shard)

    @replay.immutable
    def start_agent(self, state, desc):
        f = fiber.Fiber()
        f.add_callback(state.medium.agency.start_agent)
        # transform the reference to IRecipient.
        # agents should not keep the direct references
        # to the other agent. It is harmfull for replayability
        # which replays one agent and time, and breaks the rule
        # that agent comunicate only through messages
        f.add_callback(recipient.IRecipient)
        f.succeed(desc)
        return f


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
        f.add_callback(state.agent.get_document)
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
        bids = map(lambda x: x.bids[0], state.medium.contractors)
        best = min(bids)
        best_bid = filter(
            lambda x: x.bids[0] == best, state.medium.contractors)[0]
        params = (best_bid, message.Grant(bid_index=0), )
        state.medium.grant(params)

    def restart_contract(self):
        raise NotImplemented('TO BE DONE')

    expired=restart_contract
    aborted=restart_contract

    @replay.mutable
    def completed(self, state, reports):
        report = reports[0]
        f = fiber.Fiber()
        f.add_callback(state.agent.switch_shard)
        f.succeed(report.payload['shard'])
        return f


@document.register
class Descriptor(descriptor.Descriptor):

    document_type = 'host_agent'
