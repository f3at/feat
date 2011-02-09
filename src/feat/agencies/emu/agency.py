from feat.agencies import agency

from . import messaging
from . import database


class Agency(agency.Agency):

    def __init__(self):
        mesg = messaging.Messaging()
        db = database.Database()
        agency.Agency.__init__(self, mesg, db)
