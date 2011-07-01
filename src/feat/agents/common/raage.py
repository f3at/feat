from feat.agents.base import manager, replay, message, descriptor
from feat.common import error

__all__ = ['allocate_resource', 'AllocationManager', 'discover', 'Descriptor']


class AllocationFailedError(error.FeatError):

    def __init__(self, resources, *args, **kwargs):
        msg = "Could not allocate resources: %r" % resources
        error.FeatError.__init__(self, msg, *args, **kwargs)


def allocate_resource(agent, resources, shard=None,
                      categories={}, max_distance=None):

    def on_error(f):
        raise AllocationFailedError(resources, cause=f)

    f = discover(agent, shard)
    f.add_callback(lambda recp: agent.initiate_protocol(
        AllocationManager, recp, resources, categories, max_distance))
    f.add_callback(lambda x: x.notify_finish())
    f.add_errback(on_error)
    return f


def retrying_allocate_resource(agent, resources, shard=None,
                               categories={}, max_distance=None,
                               max_retries=3):

    def on_error(f):
        raise AllocationFailedError(resources, cause=f)

    f = discover(agent, shard)
    f.add_callback(lambda recp: agent.retrying_protocol(
        AllocationManager, recp, max_retries=max_retries,
        args=(resources, categories, max_distance, )))
    f.add_callback(lambda x: x.notify_finish())
    f.add_errback(on_error)
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
