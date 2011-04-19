from feat.agents.base import descriptor, replay, manager, message

__all__ = ['Descriptor', 'MonitorManager', 'discover', 'request_monitor']


def request_monitor(agent, shard=None):
    f = discover(agent, shard)
    f.add_callback(lambda recp: agent.initiate_protocol(
            MonitorManager, recp))
    f.add_callback(lambda x: x.notify_finish())
    return f


def discover(agent, shard=None):
    shard = shard or agent.get_own_address().shard
    return agent.discover_service(MonitorManager, timeout=1, shard=shard)


class MonitorManager(manager.BaseManager):

    protocol_id = 'request-monitor'
    announce_timeout = 6

    @replay.entry_point
    def initiate(self, state):
        self.log("initiate manager")
        msg = message.Announcement()
        state.medium.announce(msg)

    @replay.entry_point
    def closed(self, state):
        self.log("close manager")
        bids = state.medium.get_bids()
        best_bid = bids[0]
        msg = message.Grant()
        params = (best_bid, msg)
        state.medium.grant(params)


@descriptor.register("monitor_agent")
class Descriptor(descriptor.Descriptor):
    pass
