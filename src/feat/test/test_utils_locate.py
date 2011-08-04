from feat.test import common
from feat.agents.common import host
from feat.agents.base import descriptor, agent, recipient
from feat.agencies.emu import database
from feat.utils.locate import locate
from feat.common import defer


class TestLocating(common.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        self.database = database.Database()
        self.connection = self.database.get_connection()

        host1 = host.Descriptor(doc_id=u'host1')
        host2 = host.Descriptor(doc_id=u'host2')
        self.host1 = yield self.connection.save_document(host1)
        self.host2 = yield self.connection.save_document(host2)
        part1 = agent.BasePartner(recipient.IRecipient(host1),
                                  role=u'host')
        agent1 = descriptor.Descriptor(partners=[part1])
        agent2 = descriptor.Descriptor()
        self.agent1 = yield self.connection.save_document(agent1)
        self.agent2 = yield self.connection.save_document(agent2)

    @defer.inlineCallbacks
    def testLocating(self):
        host1 = yield locate(self.connection, self.host1.doc_id)
        self.assertEqual('host1', host1)
        host1 = yield locate(self.connection, self.agent1.doc_id)
        self.assertEqual('host1', host1)
        none = yield locate(self.connection, self.agent2.doc_id)
        self.assertIs(None, none)
