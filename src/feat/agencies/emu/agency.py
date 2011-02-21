from feat.agencies import agency

from feat.agencies.emu import messaging
from feat.agencies.emu import database


class Agency(agency.Agency):

    def __init__(self):
        mesg = messaging.Messaging()
        db = database.Database()
        agency.Agency.__init__(self, mesg, db)
