import paisley

from zope.interface import implements
from twisted.web import error as web_error

from feat.agencies.emu.database import Connection
from feat.common import log, decorator
from feat.agencies.emu.interface import (IConnectionFactory, ConflictError,
                                         NotFoundError)


@decorator.simple_function
def wrap_in_error_handler(method):

    def wrapped(self, *args, **kwargs):
        d = method(self, *args, **kwargs)
        d.addErrback(self.error_handler)
        return d

    return wrapped


class Database(paisley.CouchDB, log.FluLogKeeper, log.Logger):

    implements(IConnectionFactory)

    log_category = "database"

    def __init__(self, host, port, db_name):
        paisley.CouchDB.__init__(self, host, port, db_name)
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)

        self.connection = Connection(self)

    # IConnectionFactory

    def get_connection(self, agent):
        return self.connection

    # end of IConnectionFactory

    openDoc = wrap_in_error_handler(paisley.CouchDB.openDoc)
    saveDoc = wrap_in_error_handler(paisley.CouchDB.saveDoc)
    deleteDoc = wrap_in_error_handler(paisley.CouchDB.deleteDoc)

    def error_handler(self, failure):
        exception = failure.value
        msg = failure.getErrorMessage()
        if isinstance(exception, web_error.Error):
            status = int(exception.status)
            if status == 409:
                raise ConflictError(msg)
            elif status == 404:
                raise NotFoundError(msg)
            else:
                raise NotImplementedError(
                    'Behaviour for response code %d not define yet, FIXME!' %
                    status)
        else:
            failure.raiseException()
