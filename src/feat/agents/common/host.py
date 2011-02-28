from feat.agents.base import requester, replay, message
from feat.common import fiber


__all__ = ['start_agent', 'StartAgentRequester']


def start_agent(medium, recp, desc, *args, **kwargs):
    '''
    Tells remote host agent to start agent identified by desc.
    The result value of the fiber is IRecipient.
    '''
    f = fiber.Fiber()
    f.add_callback(medium.initiate_protocol, recp, desc, *args, **kwargs)
    f.add_callback(StartAgentRequester.notify_finish)
    f.succeed(StartAgentRequester)
    return f


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
        return reply.payload['agent']
