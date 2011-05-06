# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from feat import everything
from feat.agents.base import recipient, descriptor, agent, partners, replay
from feat.agents.base import dbtools
from feat.agents.common import monitor
from feat.common import log, delay, first, serialization, defer, time
from feat.common.text_helper import format_block

from feat.interface.recipient import *

from feat.test.integration import common


@common.attr(skip="This is leftover after work of Pau left by mistake. " +
             "To be deleted when Sebastien merges his work")
@common.attr('slow')
class SingleHostMonitorSimulation(common.SimulationTest):

    timeout = 20

    @defer.inlineCallbacks
    def prolog(self):
        time.scale(0.8)
        setup = format_block("""
        load('feat.test.integration.monitor')

        agency = spawn_agency()

        host_desc = descriptor_factory('host_agent')
        req_desc = descriptor_factory('request_monitor_agent')

        host_medium = agency.start_agent(host_desc)
        host_agent = host_medium.get_agent()

        host_agent.wait_for_ready()
        host_agent.start_agent(req_desc)
        """)

        yield self.process(setup)
        yield self.wait_for_idle(10)

        monitor_medium = list(self.driver.iter_agents('monitor_agent'))[0]
        self.monitor_agent = monitor_medium.get_agent()

        self.req_agent = self.driver.find_agent(
                self.get_local('req_desc')).get_agent()

    @defer.inlineCallbacks
    def tearDown(self):
        for x in self.driver.iter_agents():
            yield x.wait_for_listeners_finish()
        yield common.SimulationTest.tearDown(self)

    def testValidateProlog(self):
        self.assertEqual(1, self.count_agents('host_agent'))
        self.assertEqual(1, self.count_agents('shard_agent'))
        self.assertEqual(1, self.count_agents('monitor_agent'))
        self.assertEqual(1, self.count_agents('request_monitor_agent'))

    @defer.inlineCallbacks
    def testPartnerMonitor(self):
        yield self.req_agent.request_monitor()
        partners = self.monitor_agent.get_descriptor().partners
        self.assertEqual(3, len(partners))


@descriptor.register('monitored_agent')
class MonitoredDescriptor(descriptor.Descriptor):
    pass


@agent.register('monitored_agent')
class MonitoredAgent(agent.BaseAgent):
    pass


@descriptor.register('random-agent')
class Descriptor(descriptor.Descriptor):
    pass


@agent.register('random-agent')
class RandomAgent(agent.BaseAgent):
    '''
    Agent nobody cares to restart.
    '''

    restart_strategy = monitor.RestartStrategy.whereever

    resources = {'epu': 10}

    @replay.immutable
    def get_monitors(self, state):
        return state.partners.all_with_role(u'monitor')


@descriptor.register('bad-manager-agent')
class BadManangerDescriptor(descriptor.Descriptor):
    pass


@serialization.register
class BadHandler(partners.BasePartner):

    def on_died(self, agent, brothers, monitor):
        time = agent.get_time()
        called = agent.called()
        if called == 1:
            return partners.ResponsabilityAccepted(expiration_time=time + 2)


class Partners(partners.Partners):

    default_handler = BadHandler


@agent.register('bad-manager-agent')
class BadManagerAgent(agent.BaseAgent):
    '''
    Agent monitoring other agents. It commits to restart them once and
    does nothing about it.
    '''

    partners_class = Partners

    @replay.mutable
    def initiate(self, state):
        agent.BaseAgent.initiate(self)
        state.times_called = 0

    @replay.mutable
    def called(self, state):
        state.times_called += 1
        return state.times_called

    @replay.immutable
    def get_times_called(self, state):
        return state.times_called


@common.attr(timescale=0.05)
class RestartingSimulation(common.SimulationTest):

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        spawn_agency()
        _.start_agent(descriptor_factory('host_agent'))
        host = _.get_agent()
        wait_for_idle()

        spawn_agency()
        _.start_agent(descriptor_factory('host_agent'))

        spawn_agency()
        _.start_agent(descriptor_factory('host_agent'))
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
        self.assertEqual(1, self.count_agents('shard_agent'))
        self.assert_has_host('shard_agent')
        for host in self.hosts:
            self.assertTrue(host.query_partners('shard') is not None)
        shard_partner = self.monitor.query_partners('shard')
        self.assertEqual(2, shard_partner.instance_id)

    @common.attr(timescale=0.1)
    @defer.inlineCallbacks
    def testShardAgentAndItsHostDied(self):
        yield self.shard_medium.terminate_hard()
        yield self._kill_first_host()
        self.assertEqual(0, self.count_agents('shard_agent'))
        self.assertEqual(2, self.count_agents('host_agent'))
        yield self.monitor.handle_agent_death(recipient.IRecipient(
            self.shard_medium))
        yield self.wait_for_idle(20)
        self.assertEqual(1, self.count_agents('shard_agent'))
        self.assertEqual(2, self.count_agents('host_agent'))
        self.assert_has_host('shard_agent')
        for host in self.hosts[1:3]:
            self.assertTrue(host.query_partners('shard') is not None)

    @defer.inlineCallbacks
    def testRaageDies(self):
        yield self.raage_medium.terminate_hard()
        self.assertEqual(0, self.count_agents('raage_agent'))
        yield self.monitor.handle_agent_death(recipient.IRecipient(
            self.raage_medium))
        yield self.wait_for_idle(20)
        self.assertEqual(1, self.count_agents('raage_agent'))
        self.assert_has_host('raage_agent')

    @common.attr(timescale=0.05)
    @defer.inlineCallbacks
    def testRaageAndHisHostDie(self):
        self.assert_has_host('raage_agent')
        yield self.raage_medium.terminate_hard()
        yield self._kill_first_host()
        self.assertEqual(0, self.count_agents('raage_agent'))
        self.assertEqual(2, self.count_agents('host_agent'))
        yield self.monitor.handle_agent_death(recipient.IRecipient(
            self.raage_medium))
        yield self.wait_for_idle(20)
        self.assertEqual(1, self.count_agents('raage_agent'))
        self.assertEqual(2, self.count_agents('host_agent'))
        self.assert_has_host('raage_agent')

    def assert_has_host(self, agent_type):
        medium = first(x for x in self.driver.iter_agents(agent_type))
        self.assertTrue(medium is not None)
        agent = medium.get_agent()
        partners = agent.query_partners('all')
        host = [x for x in partners if x.role == 'host']
        self.assertEqual(1, len(host))

    def _kill_first_host(self):
        return first(self.driver.iter_agents('host_agent')).terminate_hard()

    @defer.inlineCallbacks
    def testAgentNooneCares(self):
        script = format_block("""
        host.start_agent(descriptor_factory('random-agent'))
        """)
        yield self.process(script)
        random_medium = first(self.driver.iter_agents('random-agent'))
        self.assertTrue(random_medium is not None)
        self.assert_has_host('random-agent')

        yield random_medium.terminate_hard()
        yield self.monitor.handle_agent_death(recipient.IRecipient(
            random_medium))
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
        yield self.wait_for_idle(20)
        self.assertEqual(1, self.count_agents('random-agent'))
        self.assert_has_host('random-agent')
        self.assertEqual(2, manager.get_times_called())


@common.attr(timescale=0.05)
class MonitoringMonitor(common.SimulationTest):

    def setUp(self):
        config = everything.shard_agent.ShardAgentConfiguration(
            doc_id = 'test-config',
            hosts_per_shard = 2)
        dbtools.initial_data(config)
        self.override_config('shard_agent', config)
        return common.SimulationTest.setUp(self)

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        spawn_agency()
        _.start_agent(descriptor_factory('host_agent'))
        host = _.get_agent()
        host.wait_for_ready()

        spawn_agency()
        _.start_agent(descriptor_factory('host_agent'))

        spawn_agency()
        _.start_agent(descriptor_factory('host_agent'))
        last_host = _.get_agent()
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

    def testValidateProlog(self):
        self.assertEqual(2, self.count_agents('shard_agent'))
        self.assertEqual(2, self.count_agents('monitor_agent'))
        self.assertEqual(2, self.count_agents('raage_agent'))
        self.assertEqual(3, self.count_agents('host_agent'))

    @defer.inlineCallbacks
    def testKillMonitor(self):
        yield self.monitor_mediums[0].terminate_hard()
        self.assertEqual(1, self.count_agents('monitor_agent'))

        yield self.monitors[1].handle_agent_death(
            recipient.IRecipient(self.monitor_mediums[0]))
        yield self.wait_for_idle(20)
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

        yield self.monitor_mediums[1].terminate_hard()
        yield self.host_mediums[2].terminate_hard()
        yield random_medium.terminate_hard()
        yield list(self.driver.iter_agents('shard_agent'))[1].terminate_hard()
        yield list(self.driver.iter_agents('raage_agent'))[1].terminate_hard()

        yield self.monitors[0].handle_agent_death(
            recipient.IRecipient(self.monitor_mediums[1]))

        self.assertEqual(1, self.count_agents('random-agent'))
        random_medium = first(self.driver.iter_agents('random-agent'))
        first_shard = self.hosts[0].get_own_address().shard
        self.assertEqual(first_shard, random_medium.get_descriptor().shard)

    @defer.inlineCallbacks
    def testKillAllExceptRandomAgent(self):
        '''
        This testcase first starts the agent which imitates the agent running
        in the standalone agency who is not affected by the failure.
        Expected result is that the agent is getting monitored by the new
        monitored and removes the old one.
        '''
        script = format_block("""
        last_host.start_agent(descriptor_factory('random-agent'))
        """)
        second_shard = self.hosts[2].get_own_address().shard

        yield self.process(script)
        random_medium = first(self.driver.iter_agents('random-agent'))
        yield self.monitors[1].establish_partnership(
            recipient.IRecipient(random_medium), our_role=u'monitor')

        yield self.monitor_mediums[1].terminate_hard()
        yield self.host_mediums[2].terminate_hard()
        yield list(self.driver.iter_agents('shard_agent'))[1].terminate_hard()
        yield list(self.driver.iter_agents('raage_agent'))[1].terminate_hard()

        yield self.monitors[0].handle_agent_death(
            recipient.IRecipient(self.monitor_mediums[1]))

        self.assertEqual(1, self.count_agents('random-agent'))
        random_medium = first(self.driver.iter_agents('random-agent'))
        self.assertEqual(second_shard, random_medium.get_descriptor().shard)
        monitors = [x for x in random_medium.get_descriptor().partners\
                    if x.role == u'monitor']
        self.assertEqual(1, len(monitors))
        self.assertEqual(monitors[0].recipient,
                         recipient.IRecipient(self.monitor_mediums[0]))

    def assert_monitor_in_first_shard(self):
        shard = self.hosts[0].get_own_address().shard
        monitor = first(x for x in self.driver.iter_agents('monitor_agent')\
                        if x.get_descriptor().shard == shard)
        self.assertTrue(monitor is not None)
        partners = monitor.get_agent().query_partners('all')
        host = [x for x in partners if x.role == 'host']
        self.assertEqual(1, len(host))
        return monitor.get_agent()


@common.attr(timescale=0.05)
class SimulateMultipleMonitors(common.SimulationTest):

    def setUp(self):
        config = everything.shard_agent.ShardAgentConfiguration(
            doc_id = 'test-config',
            hosts_per_shard = 1)
        dbtools.initial_data(config)
        self.override_config('shard_agent', config)
        return common.SimulationTest.setUp(self)

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        spawn_agency()
        _.start_agent(descriptor_factory('host_agent'))
        host = _.get_agent()
        host.wait_for_ready()
        host.start_agent(descriptor_factory('random-agent'))

        spawn_agency()
        _.start_agent(descriptor_factory('host_agent'))
        _.get_agent()
        _.wait_for_ready()

        spawn_agency()
        _.start_agent(descriptor_factory('host_agent'))
        last_host = _.get_agent()
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


class TestMonitorPartnerships(common.SimulationTest):

    timeout = 300

    def setUp(self):
        delay.time_scale = 1.0
        config = everything.shard_agent.ShardAgentConfiguration()
        config.doc_id = 'test-config'
        config.hosts_per_shard = 1
        dbtools.initial_data(config)
        self.override_config('shard_agent', config)
        return common.SimulationTest.setUp(self)

    def prolog(self):
        pass

    @defer.inlineCallbacks
    def testPartnerships(self):
        drv = self.driver

        def get_agent(agents, host):
            for m in agents:
                a = m.get_agent()
                hosts = a.query_partners_with_role("all", "host")
                if not hosts:
                    continue
                if hosts[0].recipient == IRecipient(host.get_agent()):
                    return m
            self.fail("Agent not found for host %s" % host)

        def check_partners(m1, m2):
            a1 = m1.get_agent()
            a2 = m2.get_agent()
            self.assertTrue(a1.find_partner(IRecipient(a2)))
            self.assertTrue(a2.find_partner(IRecipient(a1)))

        def check_not_partners(m1, m2):
            a1 = m1.get_agent()
            a2 = m2.get_agent()
            self.assertEqual(a1.find_partner(IRecipient(a2)), None)
            self.assertEqual(a2.find_partner(IRecipient(a1)), None)

        agency1 = yield drv.spawn_agency()
        ha1_desc = yield drv.descriptor_factory("host_agent")
        ha1 = yield agency1.start_agent(ha1_desc)
        ha2_desc = yield drv.descriptor_factory("host_agent")
        ha2 = yield agency1.start_agent(ha2_desc)

        yield self.wait_for_idle(20)

        monitors = list(drv.iter_agents("monitor_agent"))
        shards = list(drv.iter_agents("shard_agent"))
        self.assertEqual(len(monitors), 2)
        self.assertEqual(len(shards), 2)

        sa1 = get_agent(shards, ha1)
        ma1 = get_agent(monitors, ha1)

        sa2 = get_agent(shards, ha2)
        ma2 = get_agent(monitors, ha2)

        check_partners(ma1, ma2)

        ha3_desc = yield drv.descriptor_factory("host_agent")
        ha3 = yield agency1.start_agent(ha3_desc)

        yield self.wait_for_idle(20)

        monitors = list(drv.iter_agents("monitor_agent"))
        shards = list(drv.iter_agents("shard_agent"))
        self.assertEqual(len(monitors), 3)
        self.assertEqual(len(shards), 3)

        sa3 = get_agent(shards, ha3)
        ma3 = get_agent(monitors, ha3)

        check_partners(ma1, ma2)
        check_partners(ma1, ma3)
        check_partners(ma2, ma3)

        sa1.terminate()

        yield self.wait_for_idle(30)

        monitors = list(drv.iter_agents("monitor_agent"))
        shards = list(drv.iter_agents("shard_agent"))
        self.assertEqual(len(monitors), 3)
        self.assertEqual(len(shards), 3)

        sa1b = get_agent(shards, ha1)
        ma1b = get_agent(monitors, ha1)

        self.assertNotEqual(sa1, sa1b)
        self.assertEqual(ma1, ma1b)
        sa1 = sa1b

        check_partners(ma1, ma2)
        check_partners(ma1, ma3)
        check_partners(ma2, ma3)

        ha1.terminate()
        sa1.terminate()

        yield self.wait_for_idle(30)

        monitors = list(drv.iter_agents("monitor_agent"))
        shards = list(drv.iter_agents("shard_agent"))
        self.assertEqual(len(monitors), 3)
        self.assertEqual(len(shards), 2)

        sa2b = get_agent(shards, ha2)
        ma2b = get_agent(monitors, ha2)

        sa3b = get_agent(shards, ha3)
        ma3b = get_agent(monitors, ha3)

        self.assertEqual(sa2b, sa2)
        self.assertEqual(ma2b, ma2)

        self.assertEqual(sa3b, sa3)
        self.assertEqual(ma3b, ma3)

        check_not_partners(ma1, ma2)
        check_not_partners(ma1, ma3)
        check_partners(ma2, ma3)

        ma1.terminate()

        yield self.wait_for_idle(30)

        monitors = list(drv.iter_agents("monitor_agent"))
        self.assertEqual(len(monitors), 2)

        ma2 = get_agent(monitors, ha2)
        ma3 = get_agent(monitors, ha3)

        check_partners(ma2, ma3)

        ha4_desc = yield drv.descriptor_factory("host_agent")
        ha4 = yield agency1.start_agent(ha4_desc)

        yield self.wait_for_idle(20)

        monitors = list(drv.iter_agents("monitor_agent"))
        shards = list(drv.iter_agents("shard_agent"))
        self.assertEqual(len(monitors), 3)
        self.assertEqual(len(shards), 3)

        ma2 = get_agent(monitors, ha2)
        ma3 = get_agent(monitors, ha3)
        ma4 = get_agent(monitors, ha4)

        check_partners(ma4, ma2)
        check_partners(ma4, ma3)
        check_partners(ma2, ma3)
