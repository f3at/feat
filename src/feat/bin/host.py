#!/usr/bin/python2.6
from feat.common import run
from feat import everything


if __name__ == '__main__':
    with run.bootstrap() as agency:
        conn = run.get_db_connection(agency)
        doc = everything.host_agent.Descriptor(shard=u'lobby')
        d = conn.save_document(doc)
        d.addCallbacks(agency.start_agent, agency._error_handler)
