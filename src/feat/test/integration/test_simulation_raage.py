# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.internet import defer

from feat import everything
from feat.common import delay
from feat.test.integration import common
from feat.interface.protocols import InitiatorFailed
from feat.common.text_helper import format_block
from feat.agents.base import recipient, agent, replay, descriptor
from feat.agents.common import raage


def checkAllocation(test, agent, resources):
    _, allocated = agent.list_resource()
    test.assertEquals(allocated, resources)


def checkNoAllocated(test, a_id):
    test.assertEquals(a_id, None)


@agent.register('requesting_agent')
class RequestingAgent(agent.BaseAgent):

    @replay.mutable
    def request_resource(self, state, resources):
        shard = self.get_own_address().shard
        return raage.allocate_resource(state.medium, shard, resources)


@descriptor.register('requesting_agent')
class Descriptor(descriptor.Descriptor):
    pass


@common.attr('slow')
class SingleHostAllocationSimulation(common.SimulationTest):

    @defer.inlineCallbacks
    def prolog(self):
        delay.time_scale = 0.2
        setup = format_block("""
        agency = spawn_agency()

        host_desc = descriptor_factory('host_agent')
        shard_desc = descriptor_factory('shard_agent', 'lobby')
        raage_desc = descriptor_factory('raage_agent')
        req_desc = descriptor_factory('requesting_agent')

        host_medium = agency.start_agent(host_desc, bootstrap=True)
        host_agent = host_medium.get_agent()

        host_agent.start_agent(shard_desc)
        host_agent.start_agent(raage_desc)
        host_agent.start_agent(req_desc)
        """)
        yield self.process(setup)
        raage_medium = self.driver.find_agent(self.get_local('raage_desc'))
        self.raage_agent = raage_medium.get_agent()
        self.host_medium = self.get_local('host_medium')
        self.host_agent = self.get_local('host_agent')
        self.req_agent = self.driver.find_agent(
            self.get_local('req_desc')).get_agent()

    @defer.inlineCallbacks
    def tearDown(self):
        for x in self.driver.iter_agents():
            yield x.wait_for_listeners_finish()
        yield common.SimulationTest.tearDown(self)

    def testValidateProlog(self):
        agents = [x for x in self.driver.iter_agents()]
        self.assertEqual(4, len(agents))

    @defer.inlineCallbacks
    def testFindHost(self):
        resources = {'host': 1}
        checkAllocation(self, self.host_agent, {'host': 0})
        allocation_id, irecipient = \
                yield self.req_agent.request_resource(resources)
        checkAllocation(self, self.host_agent, resources)
        self.assertEqual(recipient.IRecipient(self.host_medium), irecipient)

    @defer.inlineCallbacks
    def testNoHostFree(self):
        resources = {'host': 1}
        allocation_id, irecipient = \
                yield self.req_agent.request_resource(resources)
        yield self.host_medium.wait_for_listeners_finish()
        checkAllocation(self, self.host_agent, resources)
        d = self.req_agent.request_resource(resources)
        self.assertFailure(d, InitiatorFailed)
        yield d

    @defer.inlineCallbacks
    def testBadResource(self):
        resources = {'beers': 999}
        d = self.req_agent.request_resource(resources)
        self.assertFailure(d, InitiatorFailed)
        yield d


@common.attr('slow')
class MultiHostAllocationSimulation(common.SimulationTest):

    @defer.inlineCallbacks
    def prolog(self):
        delay.time_scale = 0.2
        setup = format_block("""
        shard_desc = descriptor_factory('shard_agent', 'lobby')
        raage_desc = descriptor_factory('raage_agent')
        host1_desc = descriptor_factory('host_agent')
        host2_desc = descriptor_factory('host_agent')
        host3_desc = descriptor_factory('host_agent')
        req_desc = descriptor_factory('requesting_agent')

        # First agency runs the Shard, Raage, Signal and Host agents
        agency = spawn_agency()
        host1_medium = agency.start_agent(host1_desc, bootstrap=True)
        host1_agent = host1_medium.get_agent()
        host1_agent.start_agent(shard_desc)
        host1_agent.start_agent(raage_desc)
        host1_agent.start_agent(req_desc)

        # Second agency runs the host agent
        spawn_agency()
        host2_medium = _.start_agent(host2_desc)
        host2_agent = host2_medium.get_agent()

        # Third is like seccond
        spawn_agency()
        host3_medium = _.start_agent(host3_desc)
        host3_agent = host3_medium.get_agent()

        """)
        yield self.process(setup)
        self.agency = self.get_local('agency')
        raage_medium = self.driver.find_agent(self.get_local('raage_desc'))
        self.raage_agent = raage_medium.get_agent()
        req_medium = self.driver.find_agent(self.get_local('req_desc'))
        self.req_agent = req_medium.get_agent()
        host1_medium = self.agency.find_agent(self.get_local('host1_desc'))
        self.host1_agent = host1_medium.get_agent()
        host2_medium = self.driver.find_agent(self.get_local('host2_desc'))
        self.host2_agent = host2_medium.get_agent()
        host3_medium = self.driver.find_agent(self.get_local('host3_desc'))
        self.host3_agent = host3_medium.get_agent()
        self.agents = [self.host1_agent, self.host2_agent, self.host3_agent]

    @defer.inlineCallbacks
    def _waitToFinish(self, _=None):
        for x in self.driver.iter_agents():
            yield x.wait_for_listeners_finish()

    @defer.inlineCallbacks
    def _startAllocation(self, resources, count, sequencial=True):
        d_list = list()
        for i in range(count):
            d = self.req_agent.request_resource(resources)
            if sequencial:
                yield d
            else:
                d_list.append(d)
        if not sequencial:
            yield defer.DeferredList(d_list)

    def _checkAllocations(self, resources, count):
        for agent in self.agents:
            _, allocated = agent.list_resource()
            if allocated == resources:
                count -= 1
        self.assertEquals(count, 0)

    def testValidateProlog(self):
        agents = [x for x in self.driver.iter_agents()]
        self.assertEqual(6, len(agents))
        # FIXME:  Check that the agency has all the agents

    @defer.inlineCallbacks
    def testAllocateOneHost(self):
        resources = {'host': 1}
        self._checkAllocations(resources, 0)
        yield self._startAllocation(resources, 1)
        yield self._waitToFinish()
        self._checkAllocations(resources, 1)

    @defer.inlineCallbacks
    def testAllocateAllHostsSecuencially(self):
        resources = {'host': 1}
        self._checkAllocations(resources, 0)
        yield self._startAllocation(resources, 1)
        yield self._waitToFinish()
        self._checkAllocations(resources, 1)

        yield self._startAllocation(resources, 1)
        yield self._waitToFinish()
        self._checkAllocations(resources, 2)

    @defer.inlineCallbacks
    def testAllocateSomeHosts(self):
        resources = {'host': 1}
        self._checkAllocations(resources, 0)
        yield self._startAllocation(resources, 2)
        yield self._waitToFinish()
        self._checkAllocations(resources, 2)

    @defer.inlineCallbacks
    def testAllocateAllHosts(self):
        resources = {'host': 1}
        self._checkAllocations(resources, 0)
        yield self._startAllocation(resources, 3, sequencial=False)
        yield self._waitToFinish()
        self._checkAllocations(resources, 3)
