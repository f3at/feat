# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from feat import everything
from feat.common import delay, first, serialization, defer
from feat.test.integration import common
from feat.common.text_helper import format_block
from feat.agents.base import (recipient, dbtools, descriptor, agent, partners,
                              replay, )
from feat.agents.common import monitor


@common.attr('slow')
class SingleHostMonitorSimulation(common.SimulationTest):

    timeout = 20

    @defer.inlineCallbacks
    def prolog(self):
        delay.time_scale = 0.8
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
class Descriptor(descriptor.Descriptor):
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
class Descriptor(descriptor.Descriptor):
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


class RestartingSimulation(common.SimulationTest):

    @defer.inlineCallbacks
    def prolog(self):
        delay.time_scale = 0.4
        setup = format_block("""
        spawn_agency()
        _.start_agent(descriptor_factory('host_agent'))
        host = _.get_agent()
        host.wait_for_ready()

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

    @defer.inlineCallbacks
    def testShardAgentDied(self):
        shard_partner = self.monitor.query_partners('shard')
        self.assertEqual(1, shard_partner.instance_id)
        yield self.shard_medium.terminate_hard()
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
        delay.time_scale = 0.4
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
        delay.time_scale = 0.4
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

