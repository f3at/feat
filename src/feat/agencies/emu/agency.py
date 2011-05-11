from feat.agencies import agency, journaler
from feat.common import defer

from feat.agencies.emu import messaging
from feat.agencies.emu import database


class Agency(agency.Agency):

    def initiate(self):
        mesg = messaging.Messaging()
        db = database.Database()
        journal = journaler.Journaler(self)
        d = journal.initiate()
        d.addCallback(defer.drop_result, agency.Agency.initiate,
                      self, mesg, db, journal)
        return d
