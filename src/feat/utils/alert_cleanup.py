from feat.agents.alert.alert_agent import AlertService
from feat.database import view, update
from feat.common import defer


@defer.inlineCallbacks
def do_cleanup(connection, hostname):
    connection.info("Cleaning up persistent nagios services "
                    "for hostname %s", hostname)
    if not hostname:
        raise ValueError("You need to specify the hostname to clean up")
    all_services = yield connection.query_view(view.DocumentByType,
                                               **view.DocumentByType.fetch(
                                                   AlertService.type_name))
    cleaned = 0
    for service in all_services:
        if service.hostname == hostname:
            yield connection.update_document(service, update.delete)
            cleaned += 1

    connection.info("Cleaned up %d services", cleaned)
