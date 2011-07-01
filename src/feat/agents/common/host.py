from feat.agents.base import (requester, replay, message, document,
                              manager, descriptor, )
from feat.common import fiber, serialization
from feat.interface.agent import Access, Address, Storage
from feat.interface.recipient import IRecipient


__all__ = ['start_agent', 'start_agent_in_shard', 'check_categories',
           'HostDef', 'NoHostFound', 'Descriptor']


class NoHostFound(Exception):
    pass

DEFAULT_RESOURCES = {"host": 1,
                     "bandwidth": 100,
                     "epu": 500,
                     "core": 2,
                     "mem": 1000}


DEFAULT_CATEGORIES = {'access': Access.none,
                      'address': Address.none,
                      'storage': Storage.none}

DEFAULT_PORTS_RANGES = [('misc', 8000, 9000)]


@document.register
class HostDef(document.Document):

    document_type = "hostdef"

    # The resources available for this host type.
    document.field('resources', DEFAULT_RESOURCES)
    document.field('categories', DEFAULT_CATEGORIES)
    # List of ports ranges used for allocating new ports
    document.field('ports_ranges', DEFAULT_PORTS_RANGES)


def allocate_ports(agent, recp, port_num, group):
    '''
    Allocates a number of ports for a given group in a host agent

    @param port_num: Number of ports to allocate
    @type  port_num: int
    @param group:    Group for the allocation
    @type  group:    str
    '''
    return agent.call_remote(recp, "allocate_ports", port_num, group)

def release_ports(agent, recp, ports, group):
    '''
    Releases a list of ports for a given group in a host agent

    @param ports: List of ports numbers to release
    @type  ports: list
    @param group: Group for the allocation
    @type  group: str
    '''
    return agent.call_remote(recp, "release_ports", ports, group)


def start_agent(agent, recp, desc, allocation_id=None, *args, **kwargs):
    '''
    Tells remote host agent to start agent identified by desc.
    The result value of the fiber is IRecipient.
    '''
    f = fiber.Fiber()
    f.add_callback(agent.initiate_protocol, IRecipient(recp), desc,
                   allocation_id, *args, **kwargs)
    f.add_callback(StartAgentRequester.notify_finish)
    f.succeed(StartAgentRequester)
    return f


def start_agent_in_shard(agent, desc, shard):
    f = agent.discover_service(StartAgentManager, shard=shard, timeout=1)
    f.add_callback(_check_recp_not_empty, shard)
    f.add_callback(lambda recp:
                   agent.initiate_protocol(StartAgentManager, recp, desc))
    f.add_callback(StartAgentManager.notify_finish)
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


def premodify_allocation(agent, host_agent_recipient, allocation_id, **delta):
    return agent.call_remote(host_agent_recipient, "premodify_allocation",
                             allocation_id, **delta)


def apply_modification(agent, host_agent_recipient, change_id):
    return agent.call_remote(host_agent_recipient, "apply_modification",
                             change_id)


def release_modification(agent, host_agent_recipient, change_id):
    return agent.call_remote(host_agent_recipient, "release_modification",
                             change_id)


def release_resource(agent, host_agent_recipient, alloc_id):
    return agent.call_remote(host_agent_recipient, "release_resource",
                             alloc_id)



### Private module stuff ###


def _check_recp_not_empty(recp, shard):
    if len(recp) == 0:
        return fiber.fail(
            NoHostFound('No hosts found in the shard %s' % (shard, )))
    return recp


class StartAgentManager(manager.BaseManager):

    protocol_id = 'start-agent'

    @replay.entry_point
    def initiate(self, state, desc):
        payload = dict(descriptor=desc)
        msg = message.Announcement(payload=payload)
        state.medium.announce(msg)

    @replay.entry_point
    def closed(self, state):
        bids = state.medium.get_bids()
        state.medium.grant((bids[0], message.Grant(), ))

    @replay.entry_point
    def completed(self, state, reports):
        # returns the IRecipient of new agent
        return reports[0].payload


class StartAgentRequester(requester.BaseRequester):

    protocol_id = 'start-agent'
    timeout = 10

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


@descriptor.register("host_agent")
class Descriptor(descriptor.Descriptor):

    # Hostname of the machine, updated when an agent is started
    document.field('hostname', None)
