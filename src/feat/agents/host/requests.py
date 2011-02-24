from feat.agents.base import requester, replier, replay, message, recipient
from feat.common import fiber


class StartAgentRequester(requester.BaseRequester):

    protocol_id = 'start-agent'
    timeout = 10

    @replay.journaled
    def initiate(self, state, descriptor, *args, **kwargs):
        msg = message.RequestMessage()
        msg.payload['doc_id'] = descriptor.doc_id
        msg.payload['args'] = args
        msg.payload['kwargs'] = kwargs
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
