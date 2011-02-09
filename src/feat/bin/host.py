#!/usr/bin/python2.6
from feat.common import log, error_handler
from feat.agents.host import host_agent

import run

if __name__ == '__main__':
    log.FluLogKeeper.init()
    opts = run.parse_opts()

    agency = run.run_agency(opts)
    conn = run.get_db_connection(agency)
    d = conn.save_document(host_agent.Descriptor(shard=u'lobby'))
    d.addCallbacks(agency.start_agent, error_handler)
    run.run()
