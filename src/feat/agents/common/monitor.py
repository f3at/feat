from feat.agents.base import descriptor, replay, manager, message
from feat.common import enum, fiber

# To access from this module
from feat.agents.monitor.interface import IPacemakerFactory, IPacemaker
from feat.agents.monitor.pacemaker import Pacemaker, FakePacemaker


__all__ = ['Descriptor', 'MonitorManager',
           'discover', 'request_monitor',
           'RestartFailed', 'RestartStrategy',
           'IPacemakerFactory', 'IPacemaker',
           'Pacemaker', 'FakePacemaker']


class RestartFailed(Exception):
    pass


class RestartStrategy(enum.Enum):
    """
    Enum for the IAgentFactory.restart_strategy attribute
    buryme    - Don't try to restart agent, just notify everybody about the
                death.
    local     - May be be restarted but only in the same shard.
    whereever - May be restarted whereever in the cluster.
    monitor   - Special strategy used by monitoring agents. When monitor
                cannot be restarted in the shard before dying for good his
                partners will get monitored by the monitoring agent who is
                resolving this issue.
    """
    buryme, local, whereever, monitor = range(4)


def request_monitor(agent, shard=None):
    f = discover(agent, shard)
    f.add_callback(fiber.inject_param, 1,
                   agent.initiate_protocol, MonitorManager)
    f.add_callback(fiber.call_param, "notify_finish")
    return f


def discover(agent, shard=None):
    shard = shard or agent.get_own_address().shard
    return agent.discover_service(MonitorManager, timeout=1, shard=shard)


class MonitorManager(manager.BaseManager):

    protocol_id = 'request-monitor'
    announce_timeout = 6

    @replay.entry_point
    def initiate(self, state):
        self.log("Initiate manager")
        msg = message.Announcement()
        state.medium.announce(msg)

    @replay.entry_point
    def closed(self, state):
        self.log("Cose manager")
        bids = state.medium.get_bids()
        best_bid = bids[0]
        msg = message.Grant()
        params = (best_bid, msg)
        state.medium.grant(params)


@descriptor.register("monitor_agent")
class Descriptor(descriptor.Descriptor):
    pass
