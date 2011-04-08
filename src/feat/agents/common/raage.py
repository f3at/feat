from feat.agents.base import manager, replay, recipient, message
from feat.common import fiber
from feat.agencies.agency import RetryingProtocol

__all__ = ['allocate_resource', 'AllocationManager']


def allocate_resource(medium, shard, resources):
    recp = recipient.Broadcast(AllocationManager.protocol_id, shard)

    f = fiber.Fiber()
    f.add_callback(medium.retrying_protocol, recp,
                   args=(resources, ), max_retries=3)
    f.add_callback(RetryingProtocol.notify_finish)
    return f.succeed(AllocationManager)


class AllocationManager(manager.BaseManager):

    protocol_id = 'request-allocation'
    announce_timeout = 6

    @replay.entry_point
    def initiate(self, state, resources):
        self.log("initiate manager")
        state.resources = resources
        msg = message.Announcement()
        msg.payload['resources'] = state.resources
        state.medium.announce(msg)

    @replay.entry_point
    def closed(self, state):
        self.log("close manager")
        bids = state.medium.get_bids()
        best_bid = message.Bid.pick_best(bids)[0]
        msg = message.Grant()
        params = (best_bid, msg)
        state.medium.grant(params)

    @replay.entry_point
    def completed(self, state, reports):
        self.log("completed manager")
        report = reports[0]
        return report.payload['allocation_id'], report.reply_to
