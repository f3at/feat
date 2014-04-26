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
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.internet import defer

from feat.common import first
from feat.test.integration import common
from feat.common.text_helper import format_block
from feat.agencies import recipient
from feat.agents.common import host, raage
from feat.interface.agent import Access, Address, Storage
from feat.agents.application import feat


def checkAllocation(test, agent, resources):
    _, allocated = agent.list_resource()
    for key in resources:
        test.assertEquals(allocated[key], resources[key], key)


def checkNoAllocated(test, a_id):
    test.assertEquals(a_id, None)


@common.attr(timescale=0.1)
@common.attr('slow')
class SingleHostAllocationSimulation(common.SimulationTest):

    timeout = 20

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        load('feat.test.integration.resource')

        agency = spawn_agency(start_host=False)

        host_desc = descriptor_factory('host_agent')
        req_desc = descriptor_factory('requesting_agent')

        host_medium = agency.start_agent(host_desc, hostdef=hostdef)
        host_agent = host_medium.get_agent()

        wait_for_idle()
        host_agent.start_agent(req_desc)
        """)

        hostdef = host.HostDef()
        hostdef.resources = {"host": 1, "epu": 10}
        hostdef.categories = {"access": Access.private,
                              "address": Address.dynamic,
                              "storage": Storage.static}
        hostdef.ports_ranges = {"port": (1000, 1050)}

        self.set_local("hostdef", hostdef)

        yield self.process(setup)
        yield self.wait_for_idle(10)

        raage_medium = list(self.driver.iter_agents('raage_agent'))[0]
        self.raage_agent = raage_medium.get_agent()
        self.host_medium = self.get_local('host_medium')
        self.host_agent = self.get_local('host_agent')
        medium = yield self.driver.find_agent(self.get_local('req_desc'))
        self.req_agent = medium.get_agent()

    @defer.inlineCallbacks
    def testFindHost(self):
        resources = {'host': 1}
        categories = {'access': Access.private,
                      'address': Address.none,
                      'storage': Storage.static}
        checkAllocation(self, self.host_agent, {'host': 0})
        self.info('starting test')
        allocation_id, irecipient = \
                yield self.req_agent.request_resource(resources, categories)
        checkAllocation(self, self.host_agent, resources)
        self.assertEqual(recipient.IRecipient(self.host_medium), irecipient)

    @defer.inlineCallbacks
    def testModifingAllocationWithContract(self):
        # first request the same
        desc = yield self.driver.get_document(self.req_agent.get_agent_id())
        resc = desc.extract_resources()
        allocation_id, irecipient = \
                yield self.req_agent.request_resource(resc, {}, desc.doc_id)
        req_par = yield self.host_agent.find_partner(desc.doc_id)
        self.assertEqual(req_par.allocation_id, allocation_id)

        # now lests modify
        resc['port'] = 3
        resc['host'] = 1
        allocation_id, irecipient = \
                yield self.req_agent.request_resource(resc, {}, desc.doc_id)
        self.assertEqual(req_par.allocation_id, allocation_id)
        checkAllocation(self, self.host_agent, {'port': [1000, 1001, 1002],
                                                'host': 1})
        alloc = self.host_agent.get_allocation(allocation_id)
        self.assertEqual(set([1000, 1001, 1002]), alloc.alloc['port'].values)
        self.assertEqual(1, alloc.alloc['host'].value)
        self.assertEqual(1, alloc.alloc['epu'].value)

    @defer.inlineCallbacks
    def testNoHostFree(self):
        resources = {'host': 1}
        categories = {}
        allocation_id, irecipient = \
                yield self.req_agent.request_resource(resources, categories)
        yield self.wait_for_idle(5)
        checkAllocation(self, self.host_agent, resources)
        d = self.req_agent.request_resource(resources, categories)
        self.assertFailure(d, raage.AllocationFailedError)
        yield d

    @defer.inlineCallbacks
    def testBadResource(self):
        resources = {'beers': 999}
        categories = {}
        d = self.req_agent.request_resource(resources, categories)
        self.assertFailure(d, raage.AllocationFailedError)
        yield d

    @defer.inlineCallbacks
    def testBadCategory(self):
        resources = {'host': 1}
        categories = {'address': Address.fixed}
        d = self.req_agent.request_resource(resources, categories)
        self.assertFailure(d, raage.AllocationFailedError)
        yield d


@common.attr(timescale=0.1)
@common.attr('slow')
class MultiHostAllocationSimulation(common.SimulationTest):

    timeout = 20

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        load('feat.test.integration.resource')
        req_desc = descriptor_factory('requesting_agent')

        # First agency will eventually run Host, Shard, Raage and
        # Requesting agent
        agency = spawn_agency(hostdef=hostdef)
        host = agency.get_host_agent()

        wait_for_idle()
        host.start_agent(req_desc)

        # Second agency runs the host agent
        agency = spawn_agency(hostdef=hostdef)

        # Third is like second
        agency = spawn_agency(hostdef=hostdef)
        """)

        hostdef = host.HostDef()
        hostdef.resources = {"host": 1, "epu": 10}
        hostdef.categories = {"access": Access.private,
                              "address": Address.dynamic,
                              "storage": Storage.static}
        self.set_local("hostdef", hostdef)

        yield self.process(setup)
        yield self.wait_for_idle(20)

        self.agents = [x.get_agent() \
                       for x in self.driver.iter_agents('host_agent')]
        req_medium = list(self.driver.iter_agents('requesting_agent'))[0]
        self.req_agent = req_medium.get_agent()

    @defer.inlineCallbacks
    def _waitToFinish(self, _=None):
        for x in self.driver.iter_agents():
            yield x._cancel_long_running_protocols()
            yield self.wait_for_idle(5)

    @defer.inlineCallbacks
    def _startAllocation(self, resources, categories, count, sequencial=True):
        d_list = list()
        for i in range(count):
            d = self.req_agent.request_resource(resources, categories)
            if sequencial:
                yield d
            else:
                d_list.append(d)
        if not sequencial:
            yield defer.DeferredList(d_list)

    def _checkAllocations(self, resources, count):
        for agent in self.agents:
            _, allocated = agent.list_resource()
            if all([allocated[name] == value \
                    for name, value in resources.iteritems()]):
                count -= 1
        self.assertEquals(count, 0)

    def testValidateProlog(self):
        self.assertEqual(1, self.count_agents('shard_agent'))
        self.assertEqual(1, self.count_agents('raage_agent'))
        self.assertEqual(1, self.count_agents('requesting_agent'))
        self.assertEqual(3, len(self.agents))

    @defer.inlineCallbacks
    def testAllocateOneHost(self):
        resources = {'host': 1}
        categories = {'access': Access.private}
        self._checkAllocations(resources, 0)
        yield self._startAllocation(resources, categories, 1)
        yield self._waitToFinish()
        self._checkAllocations(resources, 1)

    @defer.inlineCallbacks
    def testAllocateAllHostsSecuencially(self):
        resources = {'host': 1}
        categories = {'access': Access.private}
        self._checkAllocations(resources, 0)
        yield self._startAllocation(resources, categories, 1)
        yield self._waitToFinish()
        self._checkAllocations(resources, 1)

        yield self._startAllocation(resources, categories, 1)
        yield self._waitToFinish()
        self._checkAllocations(resources, 2)

    @defer.inlineCallbacks
    def testAllocateSomeHosts(self):
        resources = {'host': 1}
        categories = {'access': Access.private}
        self._checkAllocations(resources, 0)
        yield self._startAllocation(resources, categories, 2)
        yield self._waitToFinish()
        self._checkAllocations(resources, 2)

    @common.attr(timescale=0.5)
    @defer.inlineCallbacks
    def testAllocateAllHosts(self):
        resources = {'host': 1}
        categories = {'access': Access.private}
        self._checkAllocations(resources, 0)
        yield self._startAllocation(resources, categories,
                                    3, sequencial=False)
        yield self._waitToFinish()
        self._checkAllocations(resources, 3)


@common.attr(timescale=0.1)
@common.attr('slow')
class ContractNestingSimulation(common.SimulationTest):

    timeout = 40

    def setUp(self):
        from feat.agents.shard.shard_agent import ShardAgentConfiguration
        config = ShardAgentConfiguration(
            doc_id = u'test-config',
            hosts_per_shard = 2)
        feat.initial_data(config)
        self.override_config('shard_agent', config)
        return common.SimulationTest.setUp(self)

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        # Host 1 will run Raage, Host, Shard and Requesting agents
        load('feat.test.integration.resource')
        agency = spawn_agency(hostdef=hostdef1)
        req_desc = descriptor_factory('requesting_agent')
        host = agency.get_host_agent()
        host.start_agent(req_desc)

        # Host 2 run only host agent
        agency = spawn_agency(hostdef=hostdef1)

        # Host 3 will run Shard, Host and Raage
        agency = spawn_agency(hostdef=hostdef2)

        # Host 4 will run only host agent
        agency = spawn_agency(hostdef=hostdef2)
        """)

        # host definition in first shard (no space to allocate)
        hostdef1 = host.HostDef(resources=dict(host=0, epu=10, local=1))
        self.set_local("hostdef1", hostdef1)

        # host definition in second shard (no space to allocate)
        hostdef2 = host.HostDef(resources=dict(host=1, epu=10))
        self.set_local("hostdef2", hostdef2)

        yield self.process(setup)
        yield self.wait_for_idle(20)

        raage_mediums = self.driver.iter_agents('raage_agent')
        self.raage_agents = [x.get_agent() for x in raage_mediums]
        host_mediums = self.driver.iter_agents('host_agent')
        self.host_agents = [x.get_agent() for x in host_mediums]
        self.req_agent = first(
            self.driver.iter_agents('requesting_agent')).get_agent()

    def testValidateProlog(self):
        self.assertEqual(4, self.count_agents('host_agent'))
        self.assertEqual(2, self.count_agents('shard_agent'))
        self.assertEqual(2, self.count_agents('raage_agent'))

    @common.attr(timescale=0.2)
    @defer.inlineCallbacks
    def testRequestLocalResource(self):
        self.info("Starting test")
        resources = dict(host=1)
        d = self.req_agent.request_local_resource(resources, {})
        self.assertFailure(d, raage.AllocationFailedError)
        yield d
        self.assert_allocated('host', 0)

        allocation_id, irecipient1 = \
                yield self.req_agent.request_resource({'local': 1}, {})
        self.assert_allocated('local', 1)

    @common.attr(timescale=0.1)
    @defer.inlineCallbacks
    def testRequestFromOtherShard(self):
        self.info("Starting test")
        resources = dict(host=1)
        allocation_id, irecipient1 = \
                yield self.req_agent.request_resource(resources, {})
        self.assert_allocated('host', 1)

        allocation_id, irecipient2 = \
                yield self.req_agent.request_resource(resources, {})
        self.assert_allocated('host', 2)

        shard2_hosts = map(recipient.IRecipient, self.host_agents[2:4])
        self.assertTrue(irecipient1 in shard2_hosts)
        self.assertTrue(irecipient2 in shard2_hosts)

    def assert_allocated(self, resource, expected):
        count = 0
        for agent in self.host_agents:
            _, allocated = agent.list_resource()
            count += allocated.get(resource, 0)
        self.assertEquals(expected, count,
                          "Expected %d allocated %s, found %d" %\
                          (expected, resource, count, ))
