
'''
This is empty module which is supposed to import all the modules which declare
agents, descriptors, things which needs to be declared.
'''

from feat.agents.host import host_agent
from feat.agents.shard import shard_agent
from feat.agents.raage import raage_agent
from feat.agents.dns import dns_agent
from feat.agents.monitor import monitor_agent
from feat.agents.alert import alert_agent
from feat.agents.common import host, shard, raage, dns, monitor

# Internal to register serialization adapters
from feat.common.serialization import adapters

# Internal imports for agency
from feat.agencies import contracts, requests, tasks, notifications
