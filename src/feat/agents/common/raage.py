from feat.agents.base import manager, replay, message, descriptor

__all__ = ['allocate_resource', 'AllocationManager', 'discover', 'Descriptor']


def allocate_resource(agent, resources, shard=None,
                      categories={}, max_distance=None):
    f = discover(agent, shard)
    f.add_callback(lambda recp: agent.initiate_protocol(
        AllocationManager, recp, resources, categories, max_distance))
    f.add_callback(lambda x: x.notify_finish())
    return f


def discover(agent, shard=None):
    shard = shard or agent.get_own_address().shard
    return agent.discover_service(AllocationManager, timeout=1, shard=shard)


class AllocationManager(manager.BaseManager):

    protocol_id = 'request-allocation'
    announce_timeout = 6

    @replay.entry_point
    def initiate(self, state, resources, categories, max_distance):
        self.log("initiate manager")
        state.resources = resources
        msg = message.Announcement()
        msg.max_distance = max_distance
        msg.payload['resources'] = state.resources
        msg.payload['categories'] = categories
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


@descriptor.register("raage_agent")
class Descriptor(descriptor.Descriptor):
    pass
