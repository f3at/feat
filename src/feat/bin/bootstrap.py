#!/usr/bin/python2.6
from feat.common import run
from feat.agents.host import host_agent
from feat.agents.shard import shard_agent


def start_agent(host_medium, desc, *args, **kwargs):
    agent = host_medium.get_agent()
    d = host_medium.save_document(desc)
    d.addCallback(
        lambda desc: agent.start_agent(desc.doc_id, *args, **kwargs))
    d.addErrback(host_medium.agency._error_handler)
    return d


if __name__ == '__main__':
    with run.bootstrap() as agency:
        conn = run.get_db_connection(agency)
        d = conn.save_document(host_agent.Descriptor(shard=u'lobby'))
        d.addCallbacks(agency.start_agent, agency._error_handler,
                       callbackKeywords=dict(bootstrap=True))
        d.addCallback(start_agent, shard_agent.Descriptor(shard=u'root'))
