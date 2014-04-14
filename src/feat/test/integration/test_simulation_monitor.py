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
import copy

from feat.agents.base import descriptor, agent, partners, replay, resource
from feat.agents.common import monitor, start_agent, host
from feat.agencies import recipient
from feat.common import first, serialization, defer
from feat.common.text_helper import format_block
from feat.gateway import dummies
from feat.agents.application import feat

from feat.interface.recipient import IRecipient
from feat.agents.monitor.interface import PatientState

from feat.test.integration import common
from feat.agents.monitor import monitor_agent


@feat.register_agent('dummy_monitor_agent')
class DummyMonitorAgent(agent.BaseAgent):
    pass


@feat.register_descriptor('dummy_monitor_agent')
class DummyMonitorDescriptor(descriptor.Descriptor):
    pass


@feat.register_agent('dummy_monitored_agent')
class DummyMonitoredAgent(agent.BaseAgent):
    pass


@feat.register_descriptor('dummy_monitored_agent')
class DummyMonitoredDescriptor(descriptor.Descriptor):
    pass


@common.attr('slow')
@common.attr(timescale=0.4)
class SingleHostMonitorSimulation(common.SimulationTest):

    timeout = 20

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        agency = spawn_agency(disable_monitoring=False)

        req_desc = descriptor_factory('dummy_monitor_agent')
        host_agent = agency.get_host_agent()
        host_agent.start_agent(req_desc)
        """)

        yield self.process(setup)
        yield self.wait_for_idle(10)

        monitor_medium = list(self.driver.iter_agents('monitor_agent'))[0]
        self.monitor_agent = monitor_medium.get_agent()

        medium = yield self.driver.find_agent(self.get_local('req_desc'))
        self.req_agent = medium.get_agent()

    @defer.inlineCallbacks
    def tearDown(self):
        yield common.SimulationTest.tearDown(self)

    def testValidateProlog(self):
        self.assertEqual(1, self.count_agents('host_agent'))
        self.assertEqual(1, self.count_agents('shard_agent'))
        self.assertEqual(1, self.count_agents('monitor_agent'))
        self.assertEqual(1, self.count_agents('dummy_monitor_agent'))

    @defer.inlineCallbacks
    def testPartnerMonitor(self):
        yield self.wait_for_idle(20)
        partners = self.monitor_agent.get_descriptor().partners
        self.assertEqual(5, len(partners)) # host, shard, raag, dummy, alert


@feat.register_descriptor('random-agent')
class RandomDescriptor(descriptor.Descriptor):
    pass


@feat.register_agent('random-agent')
class RandomAgent(agent.BaseAgent):
    '''
    Agent nobody cares to restart.
    '''

    restart_strategy = monitor.RestartStrategy.wherever

    resources = {'epu': 10}

    @replay.immutable
    def get_monitors(self, state):
        return state.partners.all_with_role(u'monitor')


@feat.register_descriptor('bad-manager-agent')
class BadManangerDescriptor(descriptor.Descriptor):
    pass


@serialization.register
class BadHandler(partners.BasePartner):

    def on_died(self, agent, brothers, monitor):
        time = agent.get_time()
        called = agent.called()
        if called == 1:
            return partners.ResponsabilityAccepted(expiration_time=time + 2)


class Partners(agent.Partners):

    default_handler = BadHandler


@feat.register_agent('bad-manager-agent')
class BadManagerAgent(agent.BaseAgent):
    '''
    Agent monitoring other agents. It commits to restart them once and
    does nothing about it.
    '''

    partners_class = Partners

    @replay.mutable
    def initiate(self, state):
        state.times_called = 0

    @replay.mutable
    def called(self, state):
        state.times_called += 1
        return state.times_called

    @replay.immutable
    def get_times_called(self, state):
        return state.times_called


@common.attr(timescale=0.4)
@common.attr('slow')
class RestartingSimulation(common.SimulationTest):

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        agency1 = spawn_agency()
        host = agency1.get_host_agent()

        agency2 = spawn_agency()

        agency3 = spawn_agency()
        """)
        yield self.process(setup)
        yield self.wait_for_idle(10)
        host_mediums = list(self.driver.iter_agents('host_agent'))
        for medium, index in zip(host_mediums, range(len(host_mediums))):
            medium.log_name = "HostAgent %d" % (index, )
        self.hosts = [x.get_agent() for x in host_mediums]

        monitor_medium = first(self.driver.iter_agents('monitor_agent'))
        self.monitor = monitor_medium.get_agent()
        self.shard_medium = first(self.driver.iter_agents('shard_agent'))
        self.raage_medium = first(self.driver.iter_agents('raage_agent'))

    def tearDown(self):
        del self.hosts
        del self.monitor
        del self.shard_medium
        del self.raage_medium
        return common.SimulationTest.tearDown(self)

    @common.attr(timescale=0.2)
    @defer.inlineCallbacks
    def testShardAgentDied(self):
        shard_partner = self.monitor.query_partners('shard')
        self.assertEqual(1, shard_partner.instance_id)
        yield self.shard_medium.terminate_hard()
        self.info('gere')
        self.assertEqual(0, self.count_agents('shard_agent'))
        yield self.monitor.handle_agent_death(recipient.IRecipient(
            self.shard_medium))
        yield self.wait_for_idle(20)
        yield self.wait_for(self.monitor.has_empty_outbox, 20)

        self.assertEqual(1, self.count_agents('shard_agent'))
        self.assert_has_host('shard_agent')
        for agent in self.hosts:
            self.assertTrue(agent.query_partners('shard') is not None)
        shard_partner = self.monitor.query_partners('shard')
        self.assertEqual(2, shard_partner.instance_id)

    @defer.inlineCallbacks
    def testRaageDies(self):
        yield self.raage_medium.terminate_hard()
        self.assertEqual(0, self.count_agents('raage_agent'))
        yield self.monitor.handle_agent_death(recipient.IRecipient(
            self.raage_medium))
        yield self.wait_for_idle(20)
        yield self.wait_for(self.monitor.has_empty_outbox, 20)

        self.assertEqual(1, self.count_agents('raage_agent'))
        self.assert_has_host('raage_agent')

    def assert_has_host(self, agent_type):
        medium = first(x for x in self.driver.iter_agents(agent_type))
        self.assertTrue(medium is not None)
        agent = medium.get_agent()
        partners = agent.query_partners('all')
        hosts = [x for x in partners if x.role == 'host']
        self.assertEqual(1, len(hosts))

    def _kill_first_host(self):
        medium = first(self.driver.iter_agents('host_agent'))
        recp = recipient.IRecipient(medium)
        d = medium.terminate_hard()
        d.addBoth(defer.drop_param, self.wait_for_idle, 10)
        d.addBoth(defer.override_result, recp)
        return d

    @defer.inlineCallbacks
    def testAgentNooneCares(self):
        script = format_block("""
        host.start_agent(descriptor_factory('random-agent'))
        """)
        yield self.process(script)
        random_medium = first(self.driver.iter_agents('random-agent'))
        self.assertTrue(random_medium is not None)
        yield self.wait_for_idle(20)
        self.assert_has_host('random-agent')

        yield random_medium.terminate_hard()
        yield self.monitor.handle_agent_death(recipient.IRecipient(
            random_medium))
        yield self.wait_for(self.monitor.has_empty_outbox, 20)
        yield self.wait_for_idle(20)
        self.assertEqual(1, self.count_agents('random-agent'))
        self.assert_has_host('random-agent')

    @defer.inlineCallbacks
    def testRestartedMessesUpOneTime(self):
        script = format_block("""
        host.start_agent(descriptor_factory('random-agent'))
        host.start_agent(descriptor_factory('bad-manager-agent'))
        """)
        yield self.process(script)
        random_medium = first(self.driver.iter_agents('random-agent'))
        self.assertTrue(random_medium is not None)
        manager_medium = first(self.driver.iter_agents('bad-manager-agent'))
        self.assertTrue(manager_medium is not None)
        manager = manager_medium.get_agent()
        yield manager.establish_partnership(
            recipient.IRecipient(random_medium))

        yield random_medium.terminate_hard()
        yield self.monitor.handle_agent_death(recipient.IRecipient(
            random_medium))
        yield self.wait_for(self.monitor.has_empty_outbox, 20)
        yield self.wait_for_idle(20)

        self.assertEqual(1, self.count_agents('random-agent'))
        self.assert_has_host('random-agent')
        self.assertEqual(2, manager.get_times_called())


@common.attr(timescale=0.4)
@common.attr('slow')
class MonitoringMonitor(common.SimulationTest):

    def setUp(self):
        from feat.agents.shard.shard_agent import ShardAgentConfiguration
        config = ShardAgentConfiguration(
            doc_id = 'test-config',
            hosts_per_shard = 2)
        feat.initial_data(config)
        self.override_config('shard_agent', config)
        return common.SimulationTest.setUp(self)

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        agency1 = spawn_agency(disable_monitoring=False)
        host = agency1.get_host_agent()
        host.wait_for_ready()

        agency2 = spawn_agency(disable_monitoring=False)

        agency3 = spawn_agency(disable_monitoring=False)
        last_host = agency3.get_host_agent()
        """)
        yield self.process(setup)
        yield self.wait_for_idle(10)
        self.host_mediums = list(self.driver.iter_agents('host_agent'))
        for medium, index in zip(self.host_mediums,
                                 range(len(self.host_mediums))):
            medium.log_name = "HostAgent %d" % (index, )
        self.hosts = [x.get_agent() for x in self.host_mediums]

        self.monitor_mediums = list(self.driver.iter_agents('monitor_agent'))
        for medium, index in zip(self.monitor_mediums,
                                 range(len(self.monitor_mediums))):
            medium.log_name = "MonitorAgent %d" % (index, )
        self.monitors = [x.get_agent() for x in self.monitor_mediums]

    @defer.inlineCallbacks
    def testKillMonitor(self):
        yield self.monitor_mediums[0].terminate_hard()
        self.assertEqual(1, self.count_agents('monitor_agent'))

        yield self.monitors[1].handle_agent_death(
            recipient.IRecipient(self.monitor_mediums[0]))
        yield self.wait_for_idle(20)
        yield self.wait_for(self.monitors[1].has_empty_outbox, 20)

        self.assertEqual(2, self.count_agents('monitor_agent'))
        self.assert_monitor_in_first_shard()

    @defer.inlineCallbacks
    def testKillAllInSecondShard(self):
        '''
        This testcase first starts the agent which should get migrated from
        the second shard, and than kills everything there.
        Expected result is that the agent gets migrated to first shard.
        '''
        script = format_block("""
        last_host.start_agent(descriptor_factory('random-agent'))
        """)
        yield self.process(script)
        random_medium = first(self.driver.iter_agents('random-agent'))
        yield self.monitors[1].establish_partnership(
            recipient.IRecipient(random_medium), our_role=u'monitor')

        monitor_id = self.monitor_mediums[1].get_agent_id()
        yield self.monitor_mediums[1].terminate_hard()
        yield self.host_mediums[2].terminate_hard()
        yield random_medium.terminate_hard()

        yield list(self.driver.iter_agents('shard_agent'))[1].terminate_hard()
        yield list(self.driver.iter_agents('raage_agent'))[1].terminate_hard()
        yield list(self.driver.iter_agents('alert_agent'))[1].terminate_hard()

        yield self.monitors[0].handle_agent_death(
            recipient.IRecipient(self.monitor_mediums[1]))
        yield self.wait_for(self.monitors[0].has_empty_outbox, 40)

        self.assertEqual(1, self.count_agents('random-agent'))
        random_medium = first(self.driver.iter_agents('random-agent'))
        first_shard = self.hosts[0].get_shard_id()
        self.assertEqual(first_shard, random_medium.get_descriptor().shard)

        yield self.assert_document_not_found(monitor_id)
        yield self.wait_for(self.monitors[0].has_empty_outbox, 20)

        yield self.wait_for_idle(10)

    @defer.inlineCallbacks
    def testKillAllExceptRandomAgent(self):
        '''
        This testcase first starts the agent which imitates the agent running
        in the standalone agency who is not affected by the failure.
        Expected result is that the agent commits suicide after he receives
        on_buried notification of host agent.
        '''
        script = format_block("""
        last_host.start_agent(descriptor_factory('random-agent'))
        """)
        yield self.process(script)
        random_medium = first(self.driver.iter_agents('random-agent'))
        yield self.monitors[1].establish_partnership(
                                 recipient.IRecipient(random_medium),
                                 our_role=u'monitor', partner_role="monitored")

        yield self.monitor_mediums[1].terminate_hard()
        yield self.host_mediums[2].terminate_hard()
        yield list(self.driver.iter_agents('shard_agent'))[1].terminate_hard()
        yield list(self.driver.iter_agents('raage_agent'))[1].terminate_hard()
        yield list(self.driver.iter_agents('alert_agent'))[1].terminate_hard()

        yield self.monitors[0].handle_agent_death(
            recipient.IRecipient(self.monitor_mediums[1]))

        yield self.wait_for(self.monitors[0].has_empty_outbox, 200)

        self.assertEqual(0, self.count_agents('random-agent'))

    def assert_monitor_in_first_shard(self):
        shard = self.hosts[0].get_shard_id()
        monitor = first(x for x in self.driver.iter_agents('monitor_agent')\
                        if x.get_descriptor().shard == shard)
        self.assertTrue(monitor is not None)
        partners = monitor.get_agent().query_partners('all')
        hosts = [x for x in partners if x.role == 'host']
        self.assertEqual(1, len(hosts))
        return monitor.get_agent()


@common.attr(timescale=0.4)
@common.attr('slow')
class SimulateMultipleMonitors(common.SimulationTest):

    def setUp(self):
        from feat.agents.shard.shard_agent import ShardAgentConfiguration
        config = ShardAgentConfiguration(
            doc_id = 'test-config',
            hosts_per_shard = 1)
        feat.initial_data(config)
        self.override_config('shard_agent', config)
        return common.SimulationTest.setUp(self)

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        agency1 = spawn_agency()
        host = agency1.get_host_agent()
        host.start_agent(descriptor_factory('random-agent'))

        agency2 = spawn_agency()

        agency3 = spawn_agency()
        last_host = agency3.get_host_agent()
        """)
        yield self.process(setup)
        yield self.wait_for_idle(20)

        self.random_medium = first(self.driver.iter_agents('random-agent'))
        self.agent = self.random_medium.get_agent()
        self.recp = recipient.IRecipient(self.random_medium)
        self.monitor_mediums = list(self.driver.iter_agents('monitor_agent'))
        self.monitors = [x.get_agent() for x in self.monitor_mediums]
        for agent in self.monitors:
            yield agent.propose_to(self.recp)

    @defer.inlineCallbacks
    def testKillAndNotifyLast(self):
        yield self.random_medium.terminate_hard()
        yield self.monitors[-1].handle_agent_death(self.recp)

        yield self.wait_for_idle(20)
        self.assertEqual(1, self.count_agents('random-agent'))

    @defer.inlineCallbacks
    def testKillAndNotifyFirst(self):
        yield self.random_medium.terminate_hard()
        yield self.monitors[0].handle_agent_death(self.recp)

        yield self.wait_for_idle(20)
        self.assertEqual(1, self.count_agents('random-agent'))

    @defer.inlineCallbacks
    def testKillAndNotifyAll(self):
        yield self.random_medium.terminate_hard()
        [x.handle_agent_death(self.recp) for x in self.monitors]
        yield self.wait_for_idle(40)
        self.assertEqual(1, self.count_agents('random-agent'))

    @defer.inlineCallbacks
    def testKillAndNotifyFirstAndThirdWhileSecondIsDown(self):
        yield self.random_medium.terminate_hard()
        yield self.monitor_mediums[1].terminate_hard()
        m = [self.monitors[0], self.monitors[-1]]
        defers = [x.handle_agent_death(self.recp) for x in m]
        yield defer.DeferredList(defers)
        yield self.wait_for_idle(20)
        self.assertEqual(1, self.count_agents('random-agent'))


@common.attr('slow', timescale=0.4)
class TestMonitorPartnerships(common.SimulationTest):

    timeout = 30

    configurable_attributes = ['hosts_per_shard'] \
                              + common.SimulationTest.configurable_attributes

    def get_agents(self, name):
        return list(self.driver.iter_agents(name))

    def count_agents(self, name):
        return len(self.get_agents(name))

    def get_agent(self, name, host):
        for m in self.get_agents(name):
            a = m.get_agent()
            hosts = a.query_partners_with_role("all", "host")
            if not hosts:
                continue
            if hosts[0].recipient == IRecipient(host.get_agent()):
                return m
        self.fail("Agent not found for host %s" % host)

    def check_partners(self, m1, m2):
        a1 = m1.get_agent()
        a2 = m2.get_agent()
        self.assertTrue(a1.find_partner(IRecipient(a2)))
        self.assertTrue(a2.find_partner(IRecipient(a1)))

    def check_not_partners(self, m1, m2):
        a1 = m1.get_agent()
        a2 = m2.get_agent()
        self.assertEqual(a1.find_partner(IRecipient(a2)), None)
        self.assertEqual(a2.find_partner(IRecipient(a1)), None)

    def setUp(self):
        from feat.agents.shard.shard_agent import ShardAgentConfiguration

        if self.hosts_per_shard:
            config = ShardAgentConfiguration()
            config.doc_id = 'test-config'
            config.hosts_per_shard = self.hosts_per_shard
            feat.initial_data(config)
            self.override_config('shard_agent', config)
        return common.SimulationTest.setUp(self)

    def prolog(self):
        pass

    @common.attr(hosts_per_shard=2)
    @defer.inlineCallbacks
    def testMonitorAgentPartnerships(self):
        drv = self.driver

        agency1 = yield drv.spawn_agency(start_host=False,
            disable_monitoring=False)
        ha1_desc = yield drv.descriptor_factory("host_agent")
        ha1 = yield agency1.start_agent(ha1_desc)

        yield self.wait_for_idle(20)

        ha2_desc = yield drv.descriptor_factory("host_agent")
        ha2 = yield agency1.start_agent(ha2_desc)

        yield self.wait_for_idle(20)

        ha3_desc = yield drv.descriptor_factory("host_agent")
        ha3 = yield agency1.start_agent(ha3_desc)

        yield self.wait_for_idle(20)

        self.assertEqual(self.count_agents("monitor_agent"), 2)
        self.assertEqual(self.count_agents("shard_agent"), 2)

        ma1 = self.get_agent("monitor_agent", ha1)
        ma2 = self.get_agent("monitor_agent", ha3)

        da1_desc = yield drv.descriptor_factory("dummy_monitored_agent")
        yield drv.save_document(da1_desc)

        da2_desc = yield drv.descriptor_factory("dummy_monitored_agent")
        yield drv.save_document(da2_desc)

        da3_desc = yield drv.descriptor_factory("dummy_monitored_agent")
        yield drv.save_document(da3_desc)

        yield defer.DeferredList([ha1.get_agent().start_agent(da1_desc),
                                  ha2.get_agent().start_agent(da2_desc),
                                  ha3.get_agent().start_agent(da3_desc)])

        yield self.wait_for_idle(20)

        self.assertEqual(self.count_agents("dummy_monitored_agent"), 3)

        da1 = self.get_agent("dummy_monitored_agent", ha1)
        da2 = self.get_agent("dummy_monitored_agent", ha2)
        da3 = self.get_agent("dummy_monitored_agent", ha3)

        self.check_partners(ma1, da1)
        self.check_partners(ma1, da2)
        self.check_partners(ma2, da3)

        ma1.terminate()

        yield self.wait_for_idle(20)

        self.assertEqual(self.count_agents("monitor_agent"), 2)

        ma1b = self.get_agent("monitor_agent", ha1)

        self.check_partners(ma1b, da1)
        self.check_partners(ma1b, da2)
        self.check_partners(ma2, da3)

    @common.attr(hosts_per_shard=1)
    @defer.inlineCallbacks
    def testMonitorMonitorPartnerships(self):
        drv = self.driver

        agency1 = yield drv.spawn_agency(start_host=False,
            disable_monitoring=False)
        ha1_desc = yield drv.descriptor_factory("host_agent")
        ha1 = yield agency1.start_agent(ha1_desc)
        ha2_desc = yield drv.descriptor_factory("host_agent")
        ha2 = yield agency1.start_agent(ha2_desc)

        yield self.wait_for_idle(20)

        self.assertEqual(self.count_agents("monitor_agent"), 2)
        self.assertEqual(self.count_agents("shard_agent"), 2)

        sa1 = self.get_agent("shard_agent", ha1)
        ma1 = self.get_agent("monitor_agent", ha1)

        sa2 = self.get_agent("shard_agent", ha2)
        ma2 = self.get_agent("monitor_agent", ha2)

        self.check_partners(ma1, ma2)

        ha3_desc = yield drv.descriptor_factory("host_agent")
        ha3 = yield agency1.start_agent(ha3_desc)

        yield self.wait_for_idle(20)

        self.assertEqual(self.count_agents("monitor_agent"), 3)
        self.assertEqual(self.count_agents("shard_agent"), 3)

        sa3 = self.get_agent("shard_agent", ha3)
        ma3 = self.get_agent("monitor_agent", ha3)

        self.check_partners(ma1, ma2)
        self.check_partners(ma1, ma3)
        self.check_partners(ma2, ma3)

        sa1.terminate()

        yield self.wait_for_idle(30)

        self.assertEqual(self.count_agents("monitor_agent"), 3)
        self.assertEqual(self.count_agents("shard_agent"), 3)

        # we have to terminate all structural agents or we will have
        # a never ending retrying protocol for setting up monitoring
        sa1b = self.get_agent("shard_agent", ha1)
        ma1b = self.get_agent("monitor_agent", ha1)
        ra1 = self.get_agent("raage_agent", ha1)

        self.assertNotEqual(sa1, sa1b)
        self.assertEqual(ma1, ma1b)
        sa1 = sa1b

        self.check_partners(ma1, ma2)
        self.check_partners(ma1, ma3)
        self.check_partners(ma2, ma3)

        ha1.terminate()
        sa1.terminate()
        ra1.terminate()

        yield self.wait_for_idle(30)

        self.assertEqual(self.count_agents("monitor_agent"), 3)
        self.assertEqual(self.count_agents("shard_agent"), 2)

        sa2b = self.get_agent("shard_agent", ha2)
        ma2b = self.get_agent("monitor_agent", ha2)

        sa3b = self.get_agent("shard_agent", ha3)
        ma3b = self.get_agent("monitor_agent", ha3)

        self.assertEqual(sa2b, sa2)
        self.assertEqual(ma2b, ma2)

        self.assertEqual(sa3b, sa3)
        self.assertEqual(ma3b, ma3)

        self.check_not_partners(ma1, ma2)
        self.check_not_partners(ma1, ma3)
        self.check_partners(ma2, ma3)

        ma1.terminate()

        yield self.wait_for_idle(30)

        self.assertEqual(self.count_agents("monitor_agent"), 2)

        ma2 = self.get_agent("monitor_agent", ha2)
        ma3 = self.get_agent("monitor_agent", ha3)

        self.check_partners(ma2, ma3)

        ha4_desc = yield drv.descriptor_factory("host_agent")
        ha4 = yield agency1.start_agent(ha4_desc)

        yield self.wait_for_idle(20)

        self.assertEqual(self.count_agents("monitor_agent"), 3)
        self.assertEqual(self.count_agents("shard_agent"), 3)

        ma2 = self.get_agent("monitor_agent", ha2)
        ma3 = self.get_agent("monitor_agent", ha3)
        ma4 = self.get_agent("monitor_agent", ha4)

        self.check_partners(ma4, ma2)
        self.check_partners(ma4, ma3)
        self.check_partners(ma2, ma3)

        yield self.wait_for_idle(20)


@serialization.register
class DummyPartner(agent.BasePartner):

    type_name = 'dummy:monitor->agent'

    def initiate(self, agent):
        agent.add_call(self.recipient, "initiate")

    def on_goodbye(self, agent):
        agent.add_call(self.recipient, "goodbye")

    def on_died(self, agent, brothers, monitor):
        agent.add_call(self.recipient, "died")

    def on_restarted(self, agent):
        agent.add_call(self.recipient, "restarted")

    def on_buried(self, agent):
        agent.add_call(self.recipient, "buried")


@serialization.register
class DummyMonitorPartner(monitor.PartnerMixin, DummyPartner):

    type_name = 'dummy:monitor->monitor'


class DummyPartners(agent.Partners):

    default_handler = DummyPartner

    partners.has_many('monitors', 'monitor_agent', DummyMonitorPartner)


class DummyAgent(agent.BaseAgent):

    partners_class = DummyPartners

    @replay.mutable
    def initiate(self, state):
        state.calls = {}

    @replay.mutable
    def add_call(self, state, recipient, name):
        if recipient.key not in state.calls:
            state.calls[recipient.key] = []
        state.calls[recipient.key].append(name)

    @replay.immutable
    def get_calls(self, state):
        return copy.deepcopy(state.calls)


@feat.register_agent("test_buryme_agent")
class DummyBuryMeAgent(DummyAgent):

    restart_strategy = monitor.RestartStrategy.buryme


@feat.register_descriptor("test_buryme_agent")
class DummyBuryMeDescriptor(descriptor.Descriptor):
    pass


@feat.register_agent('test_local_agent')
class DummyLocalAgent(DummyAgent):

    restart_strategy = monitor.RestartStrategy.local


@feat.register_descriptor('test_local_agent')
class DummyLocalDescriptor(descriptor.Descriptor):
    pass


@feat.register_agent('test_wherever_agent')
class DummyWhereverAgent(DummyAgent):

    restart_strategy = monitor.RestartStrategy.wherever


@feat.register_descriptor('test_wherever_agent')
class DummyWhereverDescriptor(descriptor.Descriptor):
    pass


@common.attr('slow', timescale=0.4)
class TestRealMonitoring(common.SimulationTest):

    def setUp(self):
        # Overriding monitor configuration
        monitor_conf = monitor_agent.MonitorAgentConfiguration()
        monitor_conf.heartbeat_period = 2
        monitor_conf.heartbeat_dying_skips = 1.5
        monitor_conf.heartbeat_death_skips = 3
        monitor_conf.host_quarantine_length = 2
        monitor_conf.self_quarantine_length = 3
        monitor_conf.enable_quarantine = True
        monitor_conf.control_period = 0.2
        monitor_conf.notification_period = 1
        feat.initial_data(monitor_conf)
        self.override_config('monitor_agent', monitor_conf)
        return common.SimulationTest.setUp(self)

    def tearDown(self):
        for m in self.driver.iter_agents("monitor_agent"):
            a = m.get_agent()
            a.pause()
        return  common.SimulationTest.tearDown(self)

    @defer.inlineCallbacks
    def wait_monitored(self, agency_agent, agency_monitor, timeout):

        def check():
            for partner in agency_monitor.get_agent().query_partners("all"):
                if partner.recipient == IRecipient(agency_agent.get_agent()):
                    return True
            return False

        yield self.wait_for(check, timeout)

    def get_agents(self, name):
        return list(self.driver.iter_agents(name))

    def count_agents(self, name):
        return len(self.get_agents(name))

    def get_agent(self, name, host):
        result = []
        for m in self.get_agents(name):
            a = m.get_agent()
            hosts = a.query_partners_with_role("all", "host")
            if not hosts:
                continue
            if hosts[0].recipient == IRecipient(host.get_agent()):
                result.append(m)
        if result:
            return result
        self.fail("Agent not found for host %s" % host)

    def count_partners(self, agency_agent):
        return len(list(agency_agent.get_agent().query_partners("all")))

    def make_partners(self, agency_agent1, agency_agent2):
        recipient = IRecipient(agency_agent2.get_agent())
        return agency_agent1.get_agent().establish_partnership(recipient)

    @defer.inlineCallbacks
    def wait(self, timeout, *monitors):
        for monitor in monitors:
            yield self.wait_for(monitor.get_agent().has_empty_outbox, 20)
        yield self.wait_for_idle(timeout)

    def check_status(self, agency_monitor, entry_count,
                     default=PatientState.alive, exceptions={}):
        status = agency_monitor.get_agent().get_monitoring_status()
        all_patients = {}
        for loc in status["locations"].values():
            all_patients.update(loc["patients"])
        self.assertEqual(len(all_patients), entry_count)
        for k, s in all_patients.items():
            expected = exceptions.get(k, default)
            self.assertEqual(expected, s["state"])

    def check_calls(self, agency_agent1, partner, *expected):
        recipient = IRecipient(partner.get_agent())
        key = recipient.key
        calls = agency_agent1.get_agent().get_calls()[key]
        self.assertEqual(tuple(calls), expected)

    def check_no_call(self, agency_agent1, partner):
        recipient = IRecipient(partner.get_agent())
        key = recipient.key, recipient.route
        self.assertFalse(key in agency_agent1.get_agent().get_calls())

    def check_host(self, agency_agent, agency_host):
        agent = agency_agent.get_agent()
        hosts = [IRecipient(h)
                 for h in agent.query_partners_with_role("all", "host")]
        self.assertTrue(IRecipient(agent) in hosts)

    @common.attr(hosts_per_shard=2)
    @defer.inlineCallbacks
    def testReusingAllocation(self):
        drv = self.driver

        components = ("feat.agents.monitor.interface.IIntensiveCareFactory",
                      "feat.agents.monitor.interface.IPacemakerFactory",
                      "feat.agents.monitor.interface.IClerkFactory")

        # host1 has special resource
        hostdef1 = host.HostDef()
        hostdef1.resources['special'] = 1
        agency = yield drv.spawn_agency(hostdef=hostdef1,
            disable_monitoring=False, *components)
        h1 = yield agency.get_host_agent()

        # host2 doesn't have special resource
        agency = yield drv.spawn_agency(disable_monitoring=False, *components)
        h2 = yield agency.get_host_agent()

        # now spawn a special agent

        desc = dummies.DummyWhereverStandaloneDescriptor()
        desc.resources = dict(special=resource.AllocatedScalar(1))
        desc = yield drv.save_document(desc)

        task = yield h2.initiate_protocol(start_agent.GloballyStartAgent, desc)
        yield task.notify_finish()
        yield self.wait_for_idle(20)

        dummy = first(
            drv.iter_agents('dummy_wherever_standalone'))
        host_p = dummy.get_agent().query_partners('hosts')[0]
        self.assertEqual(host_p.recipient.key, h1.get_descriptor().doc_id)

        ma = first(drv.iter_agents('monitor_agent'))
        yield self.wait_monitored(dummy, ma, 10)

        # now terminate the dummy by modifying it's descriptor,
        # we modify the resource section to append some allocation
        # let it be restarted and assert it reuses the resource
        desc = yield drv.reload_document(desc)
        desc.resources['core'] = resource.AllocatedScalar(1)
        desc = yield drv.save_document(desc)
        yield common.delay(None, 1)
        self.assertEqual(0, self.count_agents('dummy_wherever_standalone'))

        yield common.delay(None, 10)
        yield self.wait(20, ma)

        self.assertEqual(1, self.count_agents('dummy_wherever_standalone'))
        dummy = first(
            drv.iter_agents('dummy_wherever_standalone')).get_agent()
        host_p = dummy.query_partners('hosts')[0]
        _, allocated = h1.list_resource()
        self.assertEqual(1, allocated['special'])
        self.assertEqual(1, allocated['core'])

    @common.attr(hosts_per_shard=2)
    @defer.inlineCallbacks
    def testBuryMeStrategy(self):
        drv = self.driver

        components = ("feat.agents.monitor.interface.IIntensiveCareFactory",
                      "feat.agents.monitor.interface.IPacemakerFactory",
                      "feat.agents.monitor.interface.IClerkFactory")
        agency = yield drv.spawn_agency(start_host=False,
            disable_monitoring=False, *components)
        ha_desc = yield drv.descriptor_factory("host_agent")
        ha = yield agency.start_agent(ha_desc)

        yield self.wait(20)

        # Checking shard structure

        self.assertEqual(self.count_agents("monitor_agent"), 1)
        self.assertEqual(self.count_agents("raage_agent"), 1)
        self.assertEqual(self.count_agents("shard_agent"), 1)
        sa, = self.get_agent("shard_agent", ha)
        ra, = self.get_agent("raage_agent", ha)
        ma, = self.get_agent("monitor_agent", ha)

        # Waiting everything is monitored

        yield self.wait_monitored(ha, ma, 10)
        yield self.wait_monitored(sa, ma, 10)
        yield self.wait_monitored(ra, ma, 10)

        self.assertEqual(self.count_partners(ma), 4)

        self.check_status(ma, 4)

        # Starting "bury me" agents

        desc = yield drv.descriptor_factory("test_buryme_agent")
        yield drv.save_document(desc)
        yield ha.get_agent().start_agent(desc.doc_id)

        desc = yield drv.descriptor_factory("test_buryme_agent")
        yield drv.save_document(desc)
        yield ha.get_agent().start_agent(desc.doc_id)

        desc = yield drv.descriptor_factory("test_buryme_agent")
        yield drv.save_document(desc)
        yield ha.get_agent().start_agent(desc.doc_id)

        yield self.wait(20, ma)

        self.assertEqual(self.count_agents("test_buryme_agent"), 3)

        a1, a2, a3 = self.get_agent("test_buryme_agent", ha)

        # Waiting them to be monitored

        yield self.wait_monitored(a1, ma, 10)
        yield self.wait_monitored(a2, ma, 10)
        yield self.wait_monitored(a3, ma, 10)

        # Make them partners to check callbacks

        yield self.make_partners(a1, a2)

        self.assertEqual(self.count_partners(ma), 7)
        self.check_status(ma, 7)

        # wait more than 3 heart beats, everything should be fine

        yield common.delay(None, 10)
        yield self.wait(20, ma)

        self.assertEqual(self.count_partners(ma), 7)
        self.check_status(ma, 7)

        # Kill the one with partnership

        yield a1.terminate_hard()

        # Nothing yet changed

        self.assertEqual(self.count_partners(ma), 7)
        self.check_status(ma, 7)

        # Waiting more than 3 hard beats, death should be detected

        yield common.delay(None, 10)
        yield self.wait(20, ma)

        self.assertEqual(self.count_partners(ma), 6)
        self.check_status(ma, 6)

        self.check_calls(a1, a2, "initiate")
        self.check_calls(a2, a1, "initiate", "buried")
        self.check_no_call(a3, a1)
        self.check_no_call(a3, a2)
        self.check_no_call(a1, a3)

        # Kill the one without partnership

        yield a3.terminate_hard()

        # Waiting more than 3 hard beats

        yield common.delay(None, 10)
        yield self.wait(20, ma)

        self.assertEqual(self.count_partners(ma), 5)
        self.check_status(ma, 5)

        self.check_no_call(a3, a2)

    @common.attr(hosts_per_shard=1)
    @defer.inlineCallbacks
    def testLocalStrategy(self):
        drv = self.driver

        components = ("feat.agents.monitor.interface.IIntensiveCareFactory",
                      "feat.agents.monitor.interface.IPacemakerFactory",
                      "feat.agents.monitor.interface.IClerkFactory")
        agency = yield drv.spawn_agency(start_host=False,
            disable_monitoring=False, *components)
        ha1_desc = yield drv.descriptor_factory("host_agent")
        ha1 = yield agency.start_agent(ha1_desc)
        ha2_desc = yield drv.descriptor_factory("host_agent")
        ha2 = yield agency.start_agent(ha2_desc)

        yield self.wait(300)

        # Checking shard structure

        self.assertEqual(self.count_agents("monitor_agent"), 2)
        self.assertEqual(self.count_agents("raage_agent"), 2)
        self.assertEqual(self.count_agents("shard_agent"), 2)
        sa1, = self.get_agent("shard_agent", ha1)
        sa2, = self.get_agent("shard_agent", ha2)
        ra1, = self.get_agent("raage_agent", ha1)
        ra2, = self.get_agent("raage_agent", ha2)
        ma1, = self.get_agent("monitor_agent", ha1)
        ma2, = self.get_agent("monitor_agent", ha2)

        # Waiting everything is monitored

        yield self.wait_monitored(ha1, ma1, 10)
        yield self.wait_monitored(sa1, ma1, 10)
        yield self.wait_monitored(ra1, ma1, 10)

        yield self.wait_monitored(ha2, ma2, 10)
        yield self.wait_monitored(sa2, ma2, 10)
        yield self.wait_monitored(ra2, ma2, 10)

        # Monitor agents are monitoring each-others
        self.assertEqual(self.count_partners(ma1), 5)
        self.assertEqual(self.count_partners(ma2), 5)
        self.check_status(ma1, 5)
        self.check_status(ma2, 5)

        # Starting "local" agents

        desc = yield drv.descriptor_factory("test_local_agent")
        yield drv.save_document(desc)
        yield ha1.get_agent().start_agent(desc.doc_id)

        desc = yield drv.descriptor_factory("test_local_agent")
        yield drv.save_document(desc)
        yield ha2.get_agent().start_agent(desc.doc_id)

        desc = yield drv.descriptor_factory("test_local_agent")
        yield drv.save_document(desc)
        yield ha2.get_agent().start_agent(desc.doc_id)

        yield self.wait(20, ma1, ma2)

        self.assertEqual(self.count_agents("test_local_agent"), 3)

        a1, = self.get_agent("test_local_agent", ha1)
        a2, a3 = self.get_agent("test_local_agent", ha2)

        # Waiting them to be monitored

        yield self.wait_monitored(a1, ma1, 10)
        yield self.wait_monitored(a2, ma2, 10)
        yield self.wait_monitored(a3, ma2, 10)

        # Make them partners to check callbacks

        yield self.make_partners(a1, a2)

        self.assertEqual(self.count_partners(ma1), 6)
        self.assertEqual(self.count_partners(ma2), 7)
        self.check_status(ma1, 6)
        self.check_status(ma2, 7)

        # wait a full three heart beats and half, everything should be fine

        yield common.delay(None, 10)

        self.assertEqual(self.count_partners(ma1), 6)
        self.assertEqual(self.count_partners(ma2), 7)
        self.check_status(ma1, 6)
        self.check_status(ma2, 7)

        # Kill the one with partnership

        yield a1.terminate_hard()

        # Nothing yet changed

        self.assertEqual(self.count_partners(ma1), 6)
        self.assertEqual(self.count_partners(ma2), 7)
        self.check_status(ma1, 6)
        self.check_status(ma2, 7)

        # Waiting more than 3 hard beats
        # death should be detected and agent restarted

        yield common.delay(None, 10)
        yield self.wait(20, ma1, ma2)

        a1b, = self.get_agent("test_local_agent", ha1)
        self.assertEqual(a1.get_agent().get_agent_id(),
                         a1b.get_agent().get_agent_id())
        self.assertNotEqual(a1.get_agent().get_instance_id(),
                            a1b.get_agent().get_instance_id())
        self.assertEqual(IRecipient(a1.get_agent()).route,
                         IRecipient(a1b.get_agent()).route)

        yield self.wait_monitored(a1b, ma1, 10)

        self.assertEqual(self.count_partners(ma1), 6)
        self.assertEqual(self.count_partners(ma2), 7)
        self.check_status(ma1, 6)
        self.check_status(ma2, 7)

        self.check_calls(a1, a2, "initiate")
        self.check_calls(a2, a1, "initiate", "died", "restarted")
        self.check_no_call(a3, a1)
        self.check_no_call(a3, a2)
        self.check_no_call(a1, a3)

        # Kill the other one

        yield a3.terminate_hard()

        # Nothing yet changed

        self.assertEqual(self.count_partners(ma1), 6)
        self.assertEqual(self.count_partners(ma2), 7)
        self.check_status(ma1, 6)
        self.check_status(ma2, 7)

        # Waiting more than 3 hard beats
        # death should be detected and agent restarted

        yield common.delay(None, 10)
        yield self.wait(20, ma1, ma2)

        a2b, a3b = self.get_agent("test_local_agent", ha2)
        self.assertEqual(a2.get_agent().get_full_id(),
                         a2b.get_agent().get_full_id())
        self.assertEqual(a3.get_agent().get_agent_id(),
                         a3b.get_agent().get_agent_id())
        self.assertNotEqual(a3.get_agent().get_instance_id(),
                            a3b.get_agent().get_instance_id())
        self.assertEqual(IRecipient(a3.get_agent()).route,
                         IRecipient(a3b.get_agent()).route)

        yield self.wait_monitored(a3b, ma2, 10)

        self.assertEqual(self.count_partners(ma1), 6)
        self.assertEqual(self.count_partners(ma2), 7)
        self.check_status(ma1, 6)
        self.check_status(ma2, 7)

        self.check_calls(a1, a2, "initiate")
        self.check_calls(a2, a1, "initiate", "died", "restarted")
        self.check_no_call(a3, a1)
        self.check_no_call(a3, a2)
        self.check_no_call(a1, a3)

    @common.attr(hosts_per_shard=1, jourfile="testWhereverStrategy.sqlite3")
    @defer.inlineCallbacks
    def testWhereverStrategy(self):
        drv = self.driver

        components = ("feat.agents.monitor.interface.IIntensiveCareFactory",
                      "feat.agents.monitor.interface.IPacemakerFactory",
                      "feat.agents.monitor.interface.IClerkFactory")
        agency = yield drv.spawn_agency(start_host=False,
            disable_monitoring=False, *components)
        ha1_desc = yield drv.descriptor_factory("host_agent")
        ha1 = yield agency.start_agent(ha1_desc)
        ha2_desc = yield drv.descriptor_factory("host_agent")
        ha2 = yield agency.start_agent(ha2_desc)

        yield self.wait(20)

        # Checking shard structure

        self.assertEqual(self.count_agents("monitor_agent"), 2)
        self.assertEqual(self.count_agents("raage_agent"), 2)
        self.assertEqual(self.count_agents("shard_agent"), 2)
        sa1, = self.get_agent("shard_agent", ha1)
        sa2, = self.get_agent("shard_agent", ha2)
        ra1, = self.get_agent("raage_agent", ha1)
        ra2, = self.get_agent("raage_agent", ha2)
        ma1, = self.get_agent("monitor_agent", ha1)
        ma2, = self.get_agent("monitor_agent", ha2)

        # Waiting everything is monitored

        yield self.wait_monitored(ha1, ma1, 10)
        yield self.wait_monitored(sa1, ma1, 10)
        yield self.wait_monitored(ra1, ma1, 10)

        yield self.wait_monitored(ha2, ma2, 10)
        yield self.wait_monitored(sa2, ma2, 10)
        yield self.wait_monitored(ra2, ma2, 10)

        # Monitor agents are monitoring each-others
        self.assertEqual(self.count_partners(ma1), 5)
        self.assertEqual(self.count_partners(ma2), 5)
        self.check_status(ma1, 5)
        self.check_status(ma2, 5)

        # Starting "local" agents

        desc = yield drv.descriptor_factory("test_wherever_agent")
        yield drv.save_document(desc)
        yield ha1.get_agent().start_agent(desc.doc_id)

        desc = yield drv.descriptor_factory("test_wherever_agent")
        yield drv.save_document(desc)
        yield ha2.get_agent().start_agent(desc.doc_id)

        desc = yield drv.descriptor_factory("test_wherever_agent")
        yield drv.save_document(desc)
        yield ha2.get_agent().start_agent(desc.doc_id)

        yield self.wait(20, ma1, ma2)

        self.assertEqual(self.count_agents("test_wherever_agent"), 3)

        a1, = self.get_agent("test_wherever_agent", ha1)
        a2, a3 = self.get_agent("test_wherever_agent", ha2)

        # Waiting them to be monitored

        yield self.wait_monitored(a1, ma1, 10)
        yield self.wait_monitored(a2, ma2, 10)
        yield self.wait_monitored(a3, ma2, 10)

        # Make them partners to check callbacks

        yield self.make_partners(a1, a2)

        self.assertEqual(self.count_partners(ma1), 6)
        self.assertEqual(self.count_partners(ma2), 7)
        self.check_status(ma1, 6)
        self.check_status(ma2, 7)

        # wait a full three heart beats and half, everything should be fine

        yield common.delay(None, 10)

        self.assertEqual(self.count_partners(ma1), 6)
        self.assertEqual(self.count_partners(ma2), 7)
        self.check_status(ma1, 6)
        self.check_status(ma2, 7)

        # Kill the one with partnership alongside the host and monitor

        yield ha1.terminate_hard()
        yield a1.terminate_hard()
        yield ma1.terminate_hard()

        # Nothing yet changed

        self.assertEqual(self.count_partners(ma1), 6)
        self.assertEqual(self.count_partners(ma2), 7)
        self.check_status(ma1, 6)
        self.check_status(ma2, 7)

        # Waiting more than 3 hard beats
        # death should be detected and agent restarted

        yield common.delay(None, 10)
        yield self.wait(40, ma2)

        agents = self.get_agent("test_wherever_agent", ha2)
        agents.remove(a2)
        agents.remove(a3)
        a1b, = agents
        self.assertEqual(a1.get_agent().get_agent_id(),
                         a1b.get_agent().get_agent_id())
        self.assertNotEqual(a1.get_agent().get_instance_id(),
                            a1b.get_agent().get_instance_id())
        self.assertNotEqual(IRecipient(a1.get_agent()).route,
                            IRecipient(a1b.get_agent()).route)

        # wait to detect the death of the monitor agent from shard 1
        yield common.delay(None, 10)
        # Now all structural agents in shard 1 should receive
        # on_buried notification and suicide
        self.assertEqual(1, self.count_agents('monitor_agent'))
        self.assertEqual(1, self.count_agents('raage_agent'))
        self.assertEqual(1, self.count_agents('shard_agent'))
        self.assertEqual(1, self.count_agents('host_agent'))
        self.assertEqual(1, self.count_agents('alert_agent'))

        a1 = a1b
        self.assertEqual(self.count_partners(ma2), 7)
        self.check_status(ma2, 7)

        self.check_calls(a1, a2, "initiate")
        self.check_calls(a2, a1, "initiate", "died", "restarted")
        self.check_no_call(a3, a1)
        self.check_no_call(a3, a2)
        self.check_no_call(a1, a3)

        # Kill the other one

        yield a3.terminate_hard()

        # Nothing yet changed

        self.assertEqual(self.count_partners(ma2), 7)
        self.check_status(ma2, 7)

        # Waiting more than 3 hard beats
        # death should be detected and agent restarted

        yield common.delay(None, 10)
        yield self.wait(20, ma2)

        agents = self.get_agent("test_wherever_agent", ha2)
        agents.remove(a1)
        agents.remove(a2)
        a3b, = agents
        self.assertEqual(a3.get_agent().get_agent_id(),
                         a3b.get_agent().get_agent_id())
        self.assertNotEqual(a3.get_agent().get_instance_id(),
                            a3b.get_agent().get_instance_id())
        self.assertEqual(IRecipient(a3.get_agent()).route,
                         IRecipient(a3b.get_agent()).route)

        yield self.wait_monitored(a3b, ma2, 10)

        self.assertEqual(self.count_partners(ma2), 7)
        self.check_status(ma2, 7)

        self.check_no_call(a1, a3)
        self.check_no_call(a2, a3)

    @common.attr(hosts_per_shard=1, jourfile="testMonitorStrategy.sqlite")
    @defer.inlineCallbacks
    def testMonitorStrategy(self):
        drv = self.driver

        components = ("feat.agents.monitor.interface.IIntensiveCareFactory",
                      "feat.agents.monitor.interface.IPacemakerFactory",
                      "feat.agents.monitor.interface.IClerkFactory")
        agency = yield drv.spawn_agency(start_host=False,
            disable_monitoring=False, *components)
        ha1_desc = yield drv.descriptor_factory("host_agent")
        ha1 = yield agency.start_agent(ha1_desc)
        ha2_desc = yield drv.descriptor_factory("host_agent")
        ha2 = yield agency.start_agent(ha2_desc)

        yield self.wait(20)

        # Checking shard structure

        self.assertEqual(self.count_agents("monitor_agent"), 2)
        self.assertEqual(self.count_agents("raage_agent"), 2)
        self.assertEqual(self.count_agents("shard_agent"), 2)
        sa1, = self.get_agent("shard_agent", ha1)
        sa2, = self.get_agent("shard_agent", ha2)
        ra1, = self.get_agent("raage_agent", ha1)
        ra2, = self.get_agent("raage_agent", ha2)
        ma1, = self.get_agent("monitor_agent", ha1)
        ma2, = self.get_agent("monitor_agent", ha2)

        # Waiting everything is monitored

        yield self.wait_monitored(ha1, ma1, 10)
        yield self.wait_monitored(sa1, ma1, 10)
        yield self.wait_monitored(ra1, ma1, 10)

        yield self.wait_monitored(ha2, ma2, 10)
        yield self.wait_monitored(sa2, ma2, 10)
        yield self.wait_monitored(ra2, ma2, 10)

        # Monitor agents are monitoring each-others
        self.assertEqual(self.count_partners(ma1), 5)
        self.assertEqual(self.count_partners(ma2), 5)
        self.check_status(ma1, 5)
        self.check_status(ma2, 5)

        # Starting "local" agents

        desc = yield drv.descriptor_factory("test_local_agent")
        yield drv.save_document(desc)
        yield ha1.get_agent().start_agent(desc.doc_id)

        desc = yield drv.descriptor_factory("test_local_agent")
        yield drv.save_document(desc)
        yield ha2.get_agent().start_agent(desc.doc_id)

        desc = yield drv.descriptor_factory("test_local_agent")
        yield drv.save_document(desc)
        yield ha2.get_agent().start_agent(desc.doc_id)

        yield self.wait(20, ma1, ma2)

        self.assertEqual(self.count_agents("test_local_agent"), 3)

        a1, = self.get_agent("test_local_agent", ha1)
        a2, a3 = self.get_agent("test_local_agent", ha2)

        # Waiting them to be monitored

        yield self.wait_monitored(a1, ma1, 10)
        yield self.wait_monitored(a2, ma2, 10)
        yield self.wait_monitored(a3, ma2, 10)

        # Make them partners to check callbacks

        yield self.make_partners(a1, a2)

        self.assertEqual(self.count_partners(ma1), 6)
        self.assertEqual(self.count_partners(ma2), 7)
        self.check_status(ma1, 6)
        self.check_status(ma2, 7)

        # wait a full three heart beats and half, everything should be fine

        yield common.delay(None, 10)

        self.assertEqual(self.count_partners(ma1), 6)
        self.assertEqual(self.count_partners(ma2), 7)
        self.check_status(ma1, 6)
        self.check_status(ma2, 7)

        # Kill a monitor

        yield ma1.terminate_hard()

        # Waiting more than 3 hard beats
        # death should be detected and agent restarted

        yield common.delay(None, 10)
        yield self.wait(20, ma2)

        ma1b, = self.get_agent("monitor_agent", ha1)
        self.assertEqual(ma1.get_agent().get_agent_id(),
                         ma1b.get_agent().get_agent_id())
        self.assertNotEqual(ma1.get_agent().get_instance_id(),
                            ma1b.get_agent().get_instance_id())
        self.assertEqual(IRecipient(ma1.get_agent()).route,
                         IRecipient(ma1b.get_agent()).route)

        yield self.wait_monitored(ma1b, ma2, 10)

        ma1 = ma1b

        self.assertEqual(self.count_partners(ma1), 6)
        self.assertEqual(self.count_partners(ma2), 7)
        self.check_status(ma1, 6)
        self.check_status(ma2, 7)

        self.check_calls(a1, a2, "initiate")
        self.check_calls(a2, a1, "initiate")
        self.check_no_call(a3, a1)
        self.check_no_call(a3, a2)
        self.check_no_call(a1, a3)

        # Kill an agent alongside of the monitor

        yield ma1.terminate_hard()
        yield a1.terminate_hard()

        # Waiting more than 3 hard beats
        # monitor death should be detected and agent restarted

        yield common.delay(None, 10)

        def check():
            desc = ma2.get_descriptor()
            return ma2.get_agent_id() not in desc.pending_notifications

        yield self.wait_for(check, 10)
        yield self.wait_for_idle(20)

        ma1b, = self.get_agent("monitor_agent", ha1)
        self.assertEqual(ma1.get_agent().get_agent_id(),
                         ma1b.get_agent().get_agent_id())
        self.assertNotEqual(ma1.get_agent().get_instance_id(),
                            ma1b.get_agent().get_instance_id())
        self.assertEqual(IRecipient(ma1.get_agent()).route,
                         IRecipient(ma1b.get_agent()).route)

        yield self.wait_monitored(ma1b, ma2, 10)

        ma1 = ma1b

        # Agent 1 death not detected yet
        self.assertEqual(self.count_partners(ma1), 6)
        self.assertEqual(self.count_partners(ma2), 7)

        # But dead indeed
        self.assertEqual(self.count_agents("test_local_agent"), 2)

        # Waiting more than 3 hard beats
        # death of dummy agent should be detected and agent restarted

        yield common.delay(None, 10)
        yield self.wait(20, ma1, ma2)

        a1b, = self.get_agent("test_local_agent", ha1)
        self.assertEqual(a1.get_agent().get_agent_id(),
                         a1b.get_agent().get_agent_id())
        self.assertNotEqual(a1.get_agent().get_instance_id(),
                            a1b.get_agent().get_instance_id())
        self.assertEqual(IRecipient(a1.get_agent()).route,
                         IRecipient(a1b.get_agent()).route)

        yield self.wait_monitored(a1b, ma1, 10)

        a1 = a1b

        self.assertEqual(self.count_partners(ma1), 6)
        self.assertEqual(self.count_partners(ma2), 7)
        self.check_status(ma1, 6)
        self.check_status(ma2, 7)

        self.check_calls(a1, a2, "initiate")
        self.check_calls(a2, a1, "initiate", "died", "restarted")
        self.check_no_call(a3, a1)
        self.check_no_call(a3, a2)
        self.check_no_call(a1, a3)
