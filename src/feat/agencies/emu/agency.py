from feat.agencies import agency, journaler
from feat.common import defer

from feat.agencies.emu import messaging
from feat.agencies.emu import database


class Agency(agency.Agency):

    def initiate(self):
        mesg = messaging.Messaging()
        db = database.Database()
        writer = journaler.SqliteWriter(self)
        journal = journaler.Journaler(self)
        journal.configure_with(writer)
        d = writer.initiate()
        d.addCallback(defer.drop_param, agency.Agency.initiate,
                      self, mesg, db, journal)
        return d
