from feat.agents.common import host
from feat.common import defer, first, log

from feat.database.interface import NotFoundError


@defer.inlineCallbacks
def do_cleanup(connection, host_agent_id):
    '''
    Performs cleanup after the host agent who left his descriptor in database.
    Deletes the descriptor and the descriptors of the partners he was hosting.
    '''
    desc = yield safe_get(connection, host_agent_id)
    if isinstance(desc, host.Descriptor):
        for partner in desc.partners:
            partner_desc = yield safe_get(connection, partner.recipient.key)
            if partner_desc:
                host_part = first(x for x in partner_desc.partners
                                  if x.role == 'host')
                if host_part is None:
                    log.warning('host_restart',
                                'Agent id: %s type: %s did not have any '
                                'host partner. So we are leaving it be.',
                                partner_desc.doc_id,
                                partner_desc.type_name)
                elif host_part.recipient.key == host_agent_id:
                    log.info('host_restart', "Deleting document with ID: %s",
                             partner_desc.doc_id)
                    yield connection.delete_document(partner_desc)
                else:
                    log.warning('host_restart',
                                "Not deleting descriptor of the agent id: %s, "
                                "agent_type: %s, as it seems to be hosted by "
                                "the host agent: %s. Although keep in mind "
                                "that he will not receive the goodbye "
                                "notification from us!",
                                partner_desc.doc_id,
                                partner_desc.type_name,
                                host_part.recipient.key)
        log.info('host_restart', "Deleting document with ID: %s",
                 desc.doc_id)
        yield connection.delete_document(desc)


def safe_get(connection, doc_id):

    def trap(fail):
        fail.trap(NotFoundError)
        return None

    d = connection.get_document(doc_id)
    d.addCallback(defer.bridge_param, log.info, 'host_restart',
                  "Fetched document with id %s", doc_id)
    d.addErrback(trap)
    return d
