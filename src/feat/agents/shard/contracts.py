from feat.agents.base import manager, replay, recipient, message
from feat.agencies.agency import RetryingProtocol
from feat.common import enum, fiber


def start_join_shard_manager(medium, *solutions):
    recp = recipient.Agent('join-shard', 'lobby')

    f = fiber.Fiber()
    f.add_callback(medium.retrying_protocol, recp, args=(solutions, ))
    f.add_callback(RetryingProtocol.notify_finish)
    return f.succeed(JoinShardManager)


class JoinShardManager(manager.BaseManager):

    protocol_id = 'join-shard'

    @replay.immutable
    def initiate(self, state, solutions):
        msg = message.Announcement()
        msg.payload['level'] = 0
        msg.payload['joining_agent'] = state.agent.get_own_address()
        msg.payload['solutions'] = solutions
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


class ActionType(enum.Enum):
    '''
    The type solution we are offering:

    join   - join the existing shard
    create - start your own ShardAgent as a child bid sender
    adopt  - used by SA looking for the parent
    '''
    (join, create, adopt) = range(3)
