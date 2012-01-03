from feat.common import defer
from feat.test.integration import common
from feat.utils import host_restart


class Test(common.SimulationTest):

    @defer.inlineCallbacks
    def testCleaningUp(self):
        self.agency1 = yield self.driver.spawn_agency(hostname=u'host1')
        yield self.wait_for_idle(10)
        self.agency2 = yield self.driver.spawn_agency(hostname=u'host2')
        yield self.wait_for_idle(10)
        self.assertEquals(2, self.count_agents('host_agent'))
        self.assertEquals(1, self.count_agents('shard_agent'))
        db = self.driver._database_connection
        host_desc = yield db.get_document('host1_1')

        yield host_restart.do_cleanup(db, 'host1_1')
        should_dissapear = [x.recipient.key for x in host_desc.partners]
        should_dissapear += 'host1_1'
        for agent_id in should_dissapear:
            doc = yield host_restart.safe_get(db, agent_id)
            self.assertIs(None, doc)
        doc = yield host_restart.safe_get(db, 'host2_2')
        self.assertIsNot(None, doc)
