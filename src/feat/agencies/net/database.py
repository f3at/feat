import sys
import os

from zope.interface import implements
from twisted.web import error as web_error

from feat.agencies.database import Connection
from feat.common import log, decorator
from feat.agencies.interface import (IDbConnectionFactory, ConflictError,
                                     NotFoundError)

from feat import extern
# Add feat/extern/paisley to the load path
sys.path.insert(0, os.path.join(extern.__path__[0], 'paisley'))

import paisley as feat_paisley


@decorator.simple_function
def wrap_in_error_handler(method):

    def wrapped(self, *args, **kwargs):
        d = method(self, *args, **kwargs)
        d.addErrback(self.error_handler)
        return d

    return wrapped


class Database(feat_paisley.CouchDB, log.FluLogKeeper, log.Logger):

    implements(IDbConnectionFactory)

    log_category = "database"

    def __init__(self, host, port, db_name):
        feat_paisley.CouchDB.__init__(self, host, port, db_name)
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)

        self.connection = Connection(self)

    # IDbConnectionFactory

    def get_connection(self):
        return self.connection

    # end of IConnectionFactory

    openDoc = wrap_in_error_handler(feat_paisley.CouchDB.openDoc)
    saveDoc = wrap_in_error_handler(feat_paisley.CouchDB.saveDoc)
    deleteDoc = wrap_in_error_handler(feat_paisley.CouchDB.deleteDoc)

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
                self.info(exception.response)
                raise NotImplementedError(
                    'Behaviour for response code %d not define yet, FIXME!' %
                    status)
        else:
            failure.raiseException()
