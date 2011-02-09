from feat.agencies import agency

from . import messaging
from . import database


class Agency(agency.Agency):

    def __init__(self, msg_host='localhost', msg_port=5672, msg_user='guest',
                 msg_password='guest', db_host='localhost', db_port=5984,
                 db_name='feat'):
        mesg = messaging.Messaging(msg_host, msg_port, msg_user, msg_password)
        db = database.Database(db_host, db_port, db_name)
        agency.Agency.__init__(self, mesg, db)
