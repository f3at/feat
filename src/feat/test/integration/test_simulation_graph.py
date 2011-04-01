import uuid

from feat import everything
from feat.test.integration import common
from feat.agents.shard import shard_agent
from feat.common import defer, delay
from feat.common.text_helper import format_block
from feat.test.common import attr
from feat.agents.base.recipient import IRecipient
from feat.agents.base.partners import FindPartnerError


class CommonMixin(object):

    def partners_of(self, agent):
        return set(map(lambda x: x.recipient.shard,
                   agent.query_partners('neighbours')))

    def shard_of(self, agent):
        self.assertIsInstance(agent, shard_agent.ShardAgent)
        return agent.get_own_address().shard

    def iter_partners(self, agent):
        '''
        Generator returning the ShardAgent instances of partners being
        neighbours of the given ShardAgent.
        '''
        for p in agent.query_partners('neighbours'):
            ag = self.driver.find_agent(p.recipient.key)
            yield ag.get_agent()


class DivorceSimulation(common.SimulationTest, CommonMixin):

    timeout = 20

    @defer.inlineCallbacks
    def prolog(self):
        delay.time_scale = 0.1
        script = format_block("""
        spawn_agency()
        _.start_agent(descriptor_factory('shard_agent', shard=uuid()))
        agent1 = _.get_agent()

        spawn_agency()
        _.start_agent(descriptor_factory('shard_agent', shard=uuid()))
        agent2 = _.get_agent()

        spawn_agency()
        _.start_agent(descriptor_factory('shard_agent', shard=uuid()))
        agent3 = _.get_agent()
        """)
        yield self.process(script)
        self.agent1, self.agent2, self.agent3 =\
                     self.get_local('agent1', 'agent2', 'agent3')
        self.alloc = list()
        for x in range(2):
            alloc = yield self.agent3.allocate_resource(neighbours=1)
            self.alloc.append(alloc.id)

    def assert_partners(self, agent, p_list):
        s_list = map(lambda x: self.shard_of(x), p_list)
        self.assertEqual(set(s_list), self.partners_of(agent))
        _, alloc = agent.list_resource()
        self.assertEqual(len(p_list), alloc['neighbours'])

    @defer.inlineCallbacks
    def test_simple_divorce(self):
        # establish partnership agent1 -> agent2
        yield self.agent1.propose_to(IRecipient(self.agent2))
        self.assert_partners(self.agent1, (self.agent2, ))
        self.assert_partners(self.agent2, (self.agent1, ))

        self.assertEqual(set([self.shard_of(self.agent1)]),
                         self.partners_of(self.agent2))
        # now put agent3 in the middle
        yield self.agent1.divorce_action(IRecipient(self.agent2),
                                         IRecipient(self.agent3),
                                         self.alloc)
        self.assert_partners(self.agent2, (self.agent3, ))
        self.assert_partners(self.agent1, (self.agent3, ))
        self.assert_partners(self.agent3, (self.agent1, self.agent2))

    @defer.inlineCallbacks
    def test_divorce_divorcee_is_a_partner(self):
        # establish partnership agent1 -> agent2
        yield self.agent1.propose_to(IRecipient(self.agent2))
        self.assert_partners(self.agent1, (self.agent2, ))
        self.assert_partners(self.agent2, (self.agent1, ))
        # establish partnership agent2 -> agent3
        yield self.agent2.propose_to(IRecipient(self.agent3))
        self.assert_partners(self.agent1, (self.agent2, ))
        self.assert_partners(self.agent2, (self.agent1, self.agent3))

        # now try to put agent3 in the middle between agent1 and agent2
        alloc, _ = self.agent3.list_resource()
        self.assertEqual(3, alloc['neighbours'])
        yield self.agent1.divorce_action(IRecipient(self.agent2),
                                         IRecipient(self.agent3),
                                         self.alloc)
        self.assert_partners(self.agent1, (self.agent3, ))
        self.assert_partners(self.agent2, (self.agent3, ))
        self.assert_partners(self.agent3, (self.agent1, self.agent2))

    @defer.inlineCallbacks
    def test_divorce_divorcer_is_a_partner(self):
        # establish partnership agent1 -> agent3
        yield self.agent1.propose_to(IRecipient(self.agent3))
        self.assert_partners(self.agent1, (self.agent3, ))
        # establish partnership agent1 -> agent2
        yield self.agent2.propose_to(IRecipient(self.agent1))
        self.assert_partners(self.agent1, (self.agent3, self.agent2))
        # now try to put agent3 in the middle between agent1 and agent2

        yield self.agent1.divorce_action(IRecipient(self.agent2),
                                         IRecipient(self.agent3),
                                         self.alloc)
        self.assert_partners(self.agent1, (self.agent3, ))
        self.assert_partners(self.agent2, (self.agent3, ))
        self.assert_partners(self.agent3, (self.agent1, self.agent2))

    @defer.inlineCallbacks
    def test_divorce_partner_unknown(self):
        # now try to put agent3 in the middle between agent1 and agent2,
        # these agents don't know about each other

        d = self.agent1.divorce_action(IRecipient(self.agent2),
                                       IRecipient(self.agent3),
                                       self.alloc)
        self.assertFailure(d, FindPartnerError)
        yield d
        self.assert_partners(self.agent1, tuple())
        self.assert_partners(self.agent2, tuple())


class GraphSimulation(common.SimulationTest, CommonMixin):

    timeout = 20

    def prolog(self):
        delay.time_scale = 0.6

    @defer.inlineCallbacks
    def start_shard(self):
        a_id = str(uuid.uuid1())
        script = format_block("""
        spawn_agency()
        _.start_agent(descriptor_factory('shard_agent', shard='%(shard)s'))
        agent = _.get_agent()
        agent.look_for_neighbours()
        """) % dict(shard=a_id)
        yield self.process(script)
        defer.returnValue(self.get_local('agent'))

    @defer.inlineCallbacks
    def test_start_one(self):
        agent = yield self.start_shard()
        self.assertIsInstance(agent, shard_agent.ShardAgent)
        self.assertEqual(set([]), self.partners_of(agent))

    @defer.inlineCallbacks
    def test_start_two(self):
        agent1 = yield self.start_shard()
        agent2 = yield self.start_shard()
        self.assertEqual(set([self.shard_of(agent1)]),
                         self.partners_of(agent2))
        self.assertEqual(set([self.shard_of(agent2)]),
                         self.partners_of(agent1))

    @defer.inlineCallbacks
    def test_start_three(self):
        agent1 = yield self.start_shard()
        agent2 = yield self.start_shard()
        agent3 = yield self.start_shard()
        self.assertEqual(set([self.shard_of(agent1), self.shard_of(agent2)]),
                         self.partners_of(agent3))
        self.assertEqual(set([self.shard_of(agent1), self.shard_of(agent3)]),
                         self.partners_of(agent2))
        self.assertEqual(set([self.shard_of(agent2), self.shard_of(agent3)]),
                         self.partners_of(agent1))

    @defer.inlineCallbacks
    def test_start_four(self):
        agent1 = yield self.start_shard()
        agent2 = yield self.start_shard()
        agent3 = yield self.start_shard()
        agent4 = yield self.start_shard()
        self.assertEqual(set([self.shard_of(agent1),
                              self.shard_of(agent2),
                              self.shard_of(agent3)]),
                         self.partners_of(agent4))
        self.assertEqual(set([self.shard_of(agent2),
                              self.shard_of(agent3),
                              self.shard_of(agent4)]),
                         self.partners_of(agent1))
        self.assertEqual(set([self.shard_of(agent1),
                              self.shard_of(agent3),
                              self.shard_of(agent4)]),
                         self.partners_of(agent2))
        self.assertEqual(set([self.shard_of(agent2),
                              self.shard_of(agent1),
                              self.shard_of(agent4)]),
                         self.partners_of(agent3))

    def _get_exp(self, *numbers, **kwargs):
        res = dict()
        res['kings'] = kwargs.get('kings', 0)
        for num, index in zip(numbers, range(len(numbers))):
            res[index] = num
        return res

    def check_structure(self, expected):
        expected_kings = expected.pop('kings')
        seen_kings = 0
        seen = dict(map(lambda x: (x, 0, ), expected.keys()))
        for medium in self.driver.iter_agents():
            agent = medium.get_agent()
            if agent.is_king():
                seen_kings += 1
            partners = self.partners_of(agent)
            seen[len(partners)] += 1
            our_shard = self.shard_of(agent)
            # check for self-partnership
            self.assertTrue(our_shard not in partners)
            # check for symetry of partnership
            for partner in self.iter_partners(agent):
                self.assertTrue(our_shard in self.partners_of(partner))
        for expectation, value in expected.iteritems():
            self.assertEqual(value, seen[expectation],
                             "Expected %d shard with %d partners, got %d. "
                             "This happend while having %d agents in total." %\
                             (value, expectation, seen[expectation],
                              self.get_total_agents()))
        self.assertEqual(expected_kings, seen_kings,
                         "Expected the graph to have %d kings, %d seen. "
                         "This happend while having %d agents in total." %\
                         (expected_kings, seen_kings, self.get_total_agents()))

    def get_total_agents(self):
        return len(list(self.driver.iter_agents()))

    @attr(timeout=100)
    @defer.inlineCallbacks
    def test_growing_upto_14(self):
        for x in range(5):
            yield self.start_shard()

        expected = self._get_exp(0, 0, 1, 4, kings=3)
        self.check_structure(expected)

        # 6th agent
        yield self.start_shard()
        expected = self._get_exp(0, 0, 2, 4, kings=2)
        self.check_structure(expected)

        # 7th agent
        yield self.start_shard()
        expected = self._get_exp(0, 0, 1, 6, kings=3)
        self.check_structure(expected)

        # 8th agent
        yield self.start_shard()
        expected = self._get_exp(0, 0, 2, 6, kings=3)
        self.check_structure(expected)

        # 9th agent
        yield self.start_shard()
        expected = self._get_exp(0, 0, 1, 8, kings=4)
        self.check_structure(expected)

        # 10th agent
        yield self.start_shard()
        expected = self._get_exp(0, 0, 2, 8, kings=3)
        self.check_structure(expected)

        # 11th agent
        yield self.start_shard()
        expected = self._get_exp(0, 0, 1, 10, kings=4)
        self.check_structure(expected)

        # 12th agent
        yield self.start_shard()
        expected = self._get_exp(0, 0, 2, 10, kings=3)
        self.check_structure(expected)

        # # 13th agent
        yield self.start_shard()
        expected = self._get_exp(0, 0, 1, 12, kings=4)
        self.check_structure(expected)

        # # 14th agent
        yield self.start_shard()
        expected = self._get_exp(0, 0, 2, 12, kings=3)
        self.check_structure(expected)
