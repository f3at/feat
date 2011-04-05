import uuid

from feat.agents.base import manager, replay, recipient, message, descriptor
from feat.agencies.agency import RetryingProtocol
from feat.common import enum, fiber


__all__ = ['start_manager', 'JoinShardManager']


def start_manager(agent):
    f = agent.discover_service(JoinShardManager, timeout=1)
    f.add_callback(lambda recp:
                   agent.initiate_protocol(JoinShardManager, recp))
    f.add_callback(JoinShardManager.notify_finish)
    return f


class JoinShardManager(manager.BaseManager):

    protocol_id = 'join-shard'
    announce_timeout = 4

    @replay.immutable
    def initiate(self, state):
        msg = message.Announcement()
        msg.payload['joining_agent'] = state.agent.get_own_address()
        state.medium.announce(msg)

    @replay.immutable
    def closed(self, state):
        bids = state.medium.get_bids()
        best_bid = message.Bid.pick_best(bids)[0]
        msg = message.Grant()
        msg.payload['joining_agent'] = state.agent.get_own_address()
        params = (best_bid, msg)
        state.medium.grant(params)

    @replay.mutable
    def completed(self, state, reports):
        pass


@replay.side_effect
def generate_shard_value():
    return str(uuid.uuid1())


@descriptor.register("shard_agent")
class Descriptor(descriptor.Descriptor):
    pass


def prepare_descriptor(agent, shard=None):
    shard = shard or generate_shard_value()
    desc = Descriptor(shard=shard)
    return agent.save_document(desc)
