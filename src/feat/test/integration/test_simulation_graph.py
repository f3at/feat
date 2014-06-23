# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.
import uuid

from feat.test.integration import common
from feat.agents.shard import shard_agent
from feat.agents.application import feat
from feat.common import defer
from feat.common.text_helper import format_block
from feat.test.common import attr
from feat.agencies.recipient import IRecipient, dummy_agent
from feat.agents.base.partners import FindPartnerError


class CommonMixin(object):

    def partners_of(self, agent):
        return set(map(lambda x: x.recipient.route,
                   agent.query_partners('neighbours')))

    def shard_of(self, agent):
        self.assertIsInstance(agent, shard_agent.ShardAgent)
        return agent.get_shard_id()

    @defer.inlineCallbacks
    def query_partners(self, agent):
        '''
        Generator returning the ShardAgent instances of partners being
        neighbours of the given ShardAgent.
        '''
        result = []
        for p in agent.query_partners('neighbours'):
            ag = yield self.driver.find_agent(p.recipient.key)
            result.append(ag.get_agent())
        defer.returnValue(result)

    def _get_exp(self, *numbers, **kwargs):
        res = dict()
        res['kings'] = kwargs.get('kings', 0)
        for num, index in zip(numbers, range(len(numbers))):
            res[index] = num
        return res

    @defer.inlineCallbacks
    def check_structure(self, expected):
        expected_kings = expected.pop('kings')
        seen_kings = 0
        seen = dict(map(lambda x: (x, 0, ), expected.keys()))
        for medium in self.driver.iter_agents('shard_agent'):
            agent = medium.get_agent()
            if agent.is_king():
                seen_kings += 1
            partners = self.partners_of(agent)
            seen[len(partners)] += 1
            our_shard = self.shard_of(agent)
            # check for self-partnership
            self.assertTrue(our_shard not in partners)
            # check for symetry of partnership
            partners = yield self.query_partners(agent)
            for partner in partners:
                self.assertTrue(our_shard in self.partners_of(partner))
        for expectation, value in expected.iteritems():
            self.assertEqual(value, seen[expectation],
                             "Expected %d shard with %d partners, got %d. "
                             "This happened while having %d agents in "
                             "total." % (
                                value, expectation, seen[expectation],
                                self.count_agents()))
        self.assertEqual(expected_kings, seen_kings,
                         "Expected the graph to have %d kings, %d seen. "
                         "This happened while having %d agents in total." % (
                            expected_kings, seen_kings, self.count_agents()))

    @defer.inlineCallbacks
    def start_host(self, join_shard=True):
        script = format_block("""
         desc = descriptor_factory('host_agent')
         agency = spawn_agency(start_host=False)
         medium = agency.start_agent(desc, run_startup=False)
         agent = medium.get_agent()
        """)
        yield self.process(script)
        agent = self.get_local('agent')
        if join_shard:
            yield agent.start_join_shard_manager()
        yield self.wait_for_idle(20)
        defer.returnValue(agent)


@attr(timescale=0.05)
class DivorceSimulation(common.SimulationTest, CommonMixin):

    timeout = 20

    @defer.inlineCallbacks
    def prolog(self):
        script = format_block("""
        agency = spawn_agency()
        agency.start_agent(descriptor_factory('shard_agent', shard=uuid()), \
        run_startup=False)
        agent1 = _.get_agent()

        agency = spawn_agency()
        agency.start_agent(descriptor_factory('shard_agent', shard=uuid()), \
        run_startup=False)
        agent2 = _.get_agent()

        agency = spawn_agency()
        agency.start_agent(descriptor_factory('shard_agent', shard=uuid()), \
        run_startup=False)
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


@attr(timescale=0.2)
@attr('slow')
class GraphSimulation(common.SimulationTest, CommonMixin):
    '''
    This test case only checks the graph of shard agents.
    '''
    timeout = 20

    @defer.inlineCallbacks
    def start_shard(self):
        a_id = str(uuid.uuid1())
        script = format_block("""
        agency = spawn_agency(start_host=False)
        desc = descriptor_factory('shard_agent', shard='%(shard)s')
        agency.start_agent(desc, run_startup=False)
        agent = _.get_agent()
        agent.look_for_neighbours()
        """) % dict(shard=a_id)
        yield self.process(script)
        defer.returnValue(self.get_local('agent'))

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


@attr(timescale=0.2)
@attr('slow')
class TestHostsAndShards(common.SimulationTest, CommonMixin):

    def setUp(self):
        config = shard_agent.ShardAgentConfiguration(
            doc_id = u'test-config',
            hosts_per_shard = 2)
        feat.initial_data(config)
        self.override_config('shard_agent', config)
        return common.SimulationTest.setUp(self)

    @attr(skip="at current buildbox it takes 3 minutes to run it.")
    @attr(timeout=100)
    @defer.inlineCallbacks
    def test_graph_growth_and_failure_handling(self):
        """
        In this testcase we grow the graph upto 6 shards.
        Then we kill one of the first shards and check the the hosts have
        rejoined correctly.
        This testcase doesn't check the third-party agent reaction for this
        process.
        """
        yield self.start_host()
        self.assertEqual(1, self.count_agents('host_agent'))
        self.assertEqual(1, self.count_agents('shard_agent'))
        self.assertEqual(1, self.count_agents('raage_agent'))
        expected = self._get_exp(1, 0, 0, 0, kings=1)
        self.check_structure(expected)
        shard_to_kill = list(self.driver.iter_agents('shard_agent'))[0]

        yield self.start_host()
        self.assertEqual(2, self.count_agents('host_agent'))
        self.assertEqual(1, self.count_agents('shard_agent'))
        self.assertEqual(1, self.count_agents('raage_agent'))
        expected = self._get_exp(1, 0, 0, 0, kings=1)
        self.check_structure(expected)

        yield self.start_host()
        self.assertEqual(3, self.count_agents('host_agent'))
        self.assertEqual(2, self.count_agents('shard_agent'))
        self.assertEqual(2, self.count_agents('raage_agent'))
        expected = self._get_exp(0, 2, 0, 0, kings=2)
        self.check_structure(expected)

        self.info('4th host starting')
        yield self.start_host()
        self.assertEqual(4, self.count_agents('host_agent'))
        self.assertEqual(2, self.count_agents('shard_agent'))
        self.assertEqual(2, self.count_agents('raage_agent'))
        expected = self._get_exp(0, 2, 0, 0, kings=2)
        self.check_structure(expected)

        self.info('5th host starting')
        yield self.start_host()
        self.assertEqual(5, self.count_agents('host_agent'))
        self.assertEqual(3, self.count_agents('shard_agent'))
        self.assertEqual(3, self.count_agents('raage_agent'))
        expected = self._get_exp(0, 0, 3, 0, kings=3)
        self.check_structure(expected)

        self.info('6th host starting')
        yield self.start_host()
        self.assertEqual(6, self.count_agents('host_agent'))
        self.assertEqual(3, self.count_agents('shard_agent'))
        self.assertEqual(3, self.count_agents('raage_agent'))
        expected = self._get_exp(0, 0, 3, 0, kings=3)
        self.check_structure(expected)

        self.info('7th host starting')
        yield self.start_host()
        self.assertEqual(7, self.count_agents('host_agent'))
        self.assertEqual(4, self.count_agents('shard_agent'))
        self.assertEqual(4, self.count_agents('raage_agent'))
        expected = self._get_exp(0, 0, 0, 4, kings=4)
        self.check_structure(expected)

        self.info('8th host starting')
        yield self.start_host()
        self.assertEqual(8, self.count_agents('host_agent'))
        self.assertEqual(4, self.count_agents('shard_agent'))
        self.assertEqual(4, self.count_agents('raage_agent'))
        expected = self._get_exp(0, 0, 0, 4, kings=4)
        self.check_structure(expected)

        self.info('9th host starting')
        yield self.start_host()
        self.assertEqual(9, self.count_agents('host_agent'))
        self.assertEqual(5, self.count_agents('shard_agent'))
        self.assertEqual(5, self.count_agents('raage_agent'))
        expected = self._get_exp(0, 0, 1, 4, kings=3)
        self.check_structure(expected)

        self.info('10th host starting')
        yield self.start_host()
        self.assertEqual(10, self.count_agents('host_agent'))
        self.assertEqual(5, self.count_agents('shard_agent'))
        self.assertEqual(5, self.count_agents('raage_agent'))
        expected = self._get_exp(0, 0, 1, 4, kings=3)
        self.check_structure(expected)

        self.info('11th host starting')
        yield self.start_host()
        self.assertEqual(11, self.count_agents('host_agent'))
        self.assertEqual(6, self.count_agents('shard_agent'))
        self.assertEqual(6, self.count_agents('raage_agent'))
        expected = self._get_exp(0, 0, 2, 4, kings=2)
        self.check_structure(expected)

        self.info('12th host starting')
        yield self.start_host()
        self.assertEqual(12, self.count_agents('host_agent'))
        self.assertEqual(6, self.count_agents('shard_agent'))
        self.assertEqual(6, self.count_agents('raage_agent'))
        expected = self._get_exp(0, 0, 2, 4, kings=2)
        self.check_structure(expected)

        self.info("Terminating the first shard agent. Key %r",
                  shard_to_kill.get_descriptor().doc_id)
        yield shard_to_kill._terminate()

        yield self.wait_for_idle(20)
        self.assertEqual(12, self.count_agents('host_agent'))
        self.assertEqual(6, self.count_agents('shard_agent'))
        self.assertEqual(6, self.count_agents('raage_agent'))
        expected = self._get_exp(0, 0, 0, 6, kings=5)
        self.check_structure(expected)
        self.driver.validate_shards()


@attr(timescale=0.1)
@attr('slow')
class TestProblemResolving(common.SimulationTest, CommonMixin):

    configurable_attributes = ['hosts'] \
                              + common.SimulationTest.configurable_attributes

    timeout = 60

    @defer.inlineCallbacks
    def prolog(self):
        self.agents = list()
        for x in range(self.hosts):
            agent = yield self.start_host(join_shard=False)
            agent.log_name = "host agent %d" % (x, )
            agent._get_state().medium.log_name = "host medium %d" % (x, )
            self.agents.append(agent)
        self.recipients = map(IRecipient, self.agents)
        self.assertEqual(self.hosts, self.count_agents())

    @attr(hosts=4)
    @defer.inlineCallbacks
    def test_simple_resolve(self):
        yield self._initiate_resolve(self.recipients)
        self.assert_resolved()

    @attr(hosts=4)
    @defer.inlineCallbacks
    def test_missing_in_the_middle(self):
        self.recipients.insert(1, dummy_agent())
        yield self._initiate_resolve(self.recipients)
        self.assert_resolved()

    @attr(hosts=4)
    @defer.inlineCallbacks
    def test_missing_in_the_front(self):
        self.recipients.insert(0, dummy_agent())
        yield self._initiate_resolve(self.recipients)
        self.assert_resolved()

    @attr(hosts=1)
    @defer.inlineCallbacks
    def test_single_host_and_two_rubbish(self):
        self.recipients.insert(0, dummy_agent())
        self.recipients.insert(0, dummy_agent())
        yield self._initiate_resolve(self.recipients)
        self.assert_resolved()

    def assert_resolved(self):
        self.assertEqual(1, self.count_agents('shard_agent'))
        for agent in self.agents:
            self.assertTrue(agent.query_partners('shard') is not None)
        shard_medium = list(self.driver.iter_agents('shard_agent'))[0]
        shard_agent = shard_medium.get_agent()
        _, allocated = shard_agent.list_resource()
        self.assertEqual(len(self.agents), allocated['hosts'])

    def _initiate_resolve(self, recp):
        d = defer.DeferredList(map(
            lambda x: x.resolve_missing_shard_agent_problem(recp),
            self.agents))
        d.addCallback(defer.drop_param, self.wait_for_idle, 20)
        return d
