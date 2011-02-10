#!/usr/bin/python2.6
from feat.common import run
from feat.agents.host import host_agent
from feat.agents.shard import shard_agent

if __name__ == '__main__':
    with run.bootstrap() as agency:
        conn = run.get_db_connection(agency)
        d = conn.save_document(host_agent.Descriptor(shard=u'lobby'))
        d.addCallbacks(agency.start_agent, agency._error_handler)
        d = conn.save_document(shard_agent.Descriptor(shard=u'root'))
        d.addCallbacks(agency.start_agent, agency._error_handler)
