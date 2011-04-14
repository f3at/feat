from feat.agents.base import replay, manager, message, recipient
from feat.common import fiber


def add_mapping(medium, prefix, ip):
    return _broadcast(medium, AddMappingManager, prefix, ip)


def remove_mapping(medium, prefix, ip):
    return _broadcast(medium, RemoveMappingManager, prefix, ip)


class DNSMappingManager(manager.BaseManager):

    announce_timeout = 3

    @replay.immutable
    def initiate(self, state, prefix, ip):
        state.prefix = prefix
        state.ip = ip
        state.medium.announce(message.Announcement())

    @replay.immutable
    def closed(self, state):
        msg = message.Grant()
        msg.payload['prefix'] = state.prefix
        msg.payload['ip'] = state.ip

        state.medium.grant([(bid, msg) for bid in state.medium.get_bids()])


class AddMappingManager(DNSMappingManager):
    protocol_id = 'add-dns-mapping'


class RemoveMappingManager(DNSMappingManager):
    protocol_id = 'remove-dns-mapping'


### Private Stuff ###


def _broadcast(medium, manager_factory, *args, **kwargs):
    recp = recipient.Broadcast(manager_factory.protocol_id, 'lobby')
    f = fiber.succeed(manager_factory)
    f.add_callback(medium.initiate_protocol, recp, *args, **kwargs)
    f.add_callback(manager_factory.notify_finish)
    return f
