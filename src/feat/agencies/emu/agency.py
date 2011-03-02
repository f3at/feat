from feat.agencies import agency

from feat.agencies.emu import messaging
from feat.agencies.emu import database


class Agency(agency.Agency):

    def initiate(self):
        mesg = messaging.Messaging()
        db = database.Database()
        return agency.Agency.initiate(self, mesg, db)
