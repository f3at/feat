import sys
import os

from zope.interface import implements
from twisted.web import error as web_error

from feat.agencies.database import Connection
from feat.common import log

from feat.agencies.interface import *

from feat import extern
# Add feat/extern/paisley to the load path
sys.path.insert(0, os.path.join(extern.__path__[0], 'paisley'))

import paisley as feat_paisley


class Database(log.FluLogKeeper, log.Logger):

    implements(IDbConnectionFactory, IDatabaseDriver)

    log_category = "database"

    def __init__(self, host, port, db_name):
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)

        self.paisley = feat_paisley.CouchDB(host, port)
        self.db_name = db_name
        self.connection = Connection(self)

    ### IDbConnectionFactory

    def get_connection(self):
        return self.connection

    ### IDatabaseDriver

    def open_doc(self, doc_id):
        d = self.paisley.openDoc(self.db_name, doc_id)
        d.addErrback(self._error_handler)
        return d

    def save_doc(self, doc, doc_id=None):
        d = self.paisley.saveDoc(self.db_name, doc, doc_id)
        d.addErrback(self._error_handler)
        return d

    def delete_doc(self, doc_id, revision):
        d = self.paisley.openDoc(self.db_name, doc_id, revision)
        d.addErrback(self._error_handler)
        return d

    ### private

    def _error_handler(self, failure):
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
