from feat.common import defer, log, first
from feat.agents.base import descriptor, dbtools
from feat.agents.common import host

from feat.agencies.interface import *


@defer.inlineCallbacks
def locate(connection, agent_id):
    '''
    Return the hostname of the agency where given agent runs or None.
    '''
    connection = IDatabaseClient(connection)
    log.log('locate', 'Locate called for agent_id: %r', agent_id)
    try:
        desc = yield connection.get_document(agent_id)
        log.log('locate', 'Got document %r', desc)
        if isinstance(desc, host.Descriptor):
            defer.returnValue(desc.hostname)
        elif isinstance(desc, descriptor.Descriptor):
            host_part = first(x for x in desc.partners if x.role == 'host')
            if host_part is None:
                log.log('locate',
                        'No host partner found in descriptor.')
                defer.returnValue(None)
            res = yield locate(connection, host_part.recipient.key)
            defer.returnValue(res)
    except NotFoundError:
        log.log('locate',
                'Host with id %r not found, returning None', agent_id)
        defer.returnValue(None)


def script():
    with dbtools.dbscript() as (d, args):

        @defer.inlineCallbacks
        def body(connection):
            if len(args) < 1:
                log.error('script', "USAGE: locate.py <agent_id>")
                return
            agent_id = args[0]
            try:
                host = yield locate(connection, agent_id)
            except Exception as e:
                log.error('script', 'ERROR: %r', e)
            log.info('script', 'Agent runs at host: %r', host)

        d.addCallback(body)
