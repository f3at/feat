from feat.agents.base import requester, replay, message, document
from feat.common import fiber

from feat.interface.recipient import IRecipient
from feat.interface.agent import Access, Address, Storage


__all__ = ['start_agent', 'StartAgentRequester']


@document.register
class HostDef(document.Document):

    document_type = "hostdef"

    # The resources available for this host type.
    document.field('resources', {})
    document.field('categories', {})


def start_agent(medium, recp, desc, allocation_id=None, *args, **kwargs):
    '''
    Tells remote host agent to start agent identified by desc.
    The result value of the fiber is IRecipient.
    '''
    f = fiber.Fiber()
    f.add_callback(medium.initiate_protocol, IRecipient(recp), desc,
                   allocation_id, *args, **kwargs)
    f.add_callback(StartAgentRequester.notify_finish)
    f.succeed(StartAgentRequester)
    return f


def check_categories(host, categories):
    for name, val in categories.iteritems():
        if ((isinstance(val, Access) and val == Access.none) or
            (isinstance(val, Address) and val == Address.none) or
            (isinstance(val, Storage) and val == Storage.none)):
            continue

        host_categories = host._get_state().categories
        if not (name in host_categories.keys() and
                host_categories[name] == val):
                return False
    return True


class StartAgentRequester(requester.BaseRequester):

    protocol_id = 'start-agent'
    timeout = 20

    @replay.journaled
    def initiate(self, state, descriptor, allocation_id, *args, **kwargs):
        msg = message.RequestMessage()
        msg.payload['doc_id'] = descriptor.doc_id
        msg.payload['args'] = args
        msg.payload['kwargs'] = kwargs
        msg.payload['allocation_id'] = allocation_id
        state.medium.request(msg)

    def got_reply(self, reply):
        return reply.payload['agent']
