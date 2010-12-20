# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from feat.agents.base import (agent, recipient, manager, message,
                              replier, requester, document, descriptor)
from feat.common import fiber
from feat.agencies import agency


@agent.register('host_agent')
class HostAgent(agent.BaseAgent):

    def initiate(self):
        agent.BaseAgent.initiate(self)

        self.medium.register_interest(StartAgentReplier)

        recp = recipient.Agent('join-shard', 'lobby')
        join_manager = self.medium.initiate_protocol(JoinShardManager, recp)
        return join_manager.notify_finish()

    @agent.update_descriptor
    def switch_shard(self, desc, shard):
        self.medium.leave_shard(desc.shard)
        desc.shard = shard
        self.medium.join_shard(shard)

    @fiber.woven
    def start_agent(self, desc):
        f = fiber.Fiber()
        f.add_callback(self.medium.agency.start_agent)
        f.add_callback(agency.AgencyAgent.get_descriptor)
        f.succeed(desc)
        return f


class StartAgentRequester(requester.BaseRequester):

    protocol_id = 'start-agent'
    timeout = 10

    def __init__(self, agent, medium, descriptor):
        requester.BaseRequester.__init__(self, agent, medium)
        self.descriptor = descriptor

    def initiate(self):
        msg = message.RequestMessage()
        msg.payload['doc_id'] = self.descriptor.doc_id
        self.medium.request(msg)

    def got_reply(self, reply):
        return reply


class StartAgentReplier(replier.BaseReplier):

    protocol_id = 'start-agent'

    @fiber.woven
    def requested(self, request):
        f = fiber.Fiber()
        f.add_callback(self.agent.medium.get_document)
        f.add_callback(self.agent.start_agent)
        f.add_callback(self._send_reply)
        f.succeed(request.payload['doc_id'])
        return f

    def _send_reply(self, descriptor):
        msg = message.ResponseMessage()
        msg.payload['shard'] = descriptor.shard
        msg.payload['doc_id'] = descriptor.doc_id
        self.medium.reply(msg)


class JoinShardManager(manager.BaseManager):

    protocol_id = 'join-shard'

    def initiate(self):
        msg = message.Announcement()
        msg.payload = dict(level=0)
        self.medium.announce(msg)

    def closed(self):
        bids = map(lambda x: x.bids[0], self.medium.contractors)
        best = min(bids)
        best_bid = filter(
            lambda x: x.bids[0] == best, self.medium.contractors)[0]
        params = (best_bid, message.Grant(bid_index=0), )
        self.medium.grant(params)

    def restart_contract(self):
        raise NotImplemented('TO BE DONE')

    expired=restart_contract
    aborted=restart_contract

    @fiber.woven
    def completed(self, reports):
        report = reports[0]
        f = fiber.Fiber()
        f.add_callback(self.agent.switch_shard)
        f.succeed(report.payload['shard'])
        return f


@document.register
class Descriptor(descriptor.Descriptor):

    document_type = 'host_agent'
