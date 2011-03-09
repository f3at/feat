# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.trial.unittest import SkipTest, FailTest
from twisted.internet import defer

from feat.test import common
from feat.common import delay
from feat.simulation import driver
from feat.agencies import replay


attr = common.attr


class IntegrationTest(common.TestCase):
    pass


class SimulationTest(common.TestCase):

    configurable_attributes = ['skip_replayability']
    skip_replayability = False

    def setUp(self):
        delay.time_scale = 1
        self.driver = driver.Driver()
        return self.prolog()

    def process(self, script):
        d = self.cb_after(None, self.driver._parser, 'on_finish')
        self.driver.process(script)
        return d

    def get_local(self, name):
        return self.driver._parser.get_local(name)

    @defer.inlineCallbacks
    def tearDown(self):
        for x in self.driver.iter_agents():
            yield x.wait_for_listeners_finish()
        yield common.TestCase.tearDown(self)
        if not self.skip_replayability:
            self.log("Test finished, now validating replayability.")
            for agency in self.driver._agencies:
                self._validate_replay_on_agency(agency)
        else:
            print "\n\033[91mFIXME: \033[0mReplayability test skipped: %s\n" %\
                  self.skip_replayability

    def _validate_replay_on_agency(self, agency):
        for agent in agency._agents:
            self._validate_replay_on_agent(agency, agent)

    def _validate_replay_on_agent(self, agency, agent):
        aid = agent.get_descriptor().doc_id
        self.log("Validating replay of %r with id: %s",
                 agent.agent.__class__.__name__, aid)

        entries = [entry for entry in agency._journal_entries\
                   if entry[0] == aid]
        self.log("Found %d entries of this agent.", len(entries))

        r = replay.Replay(iter(entries), aid)
        for entry in r:
            entry.apply()

        agent_snapshot, listeners = agent.snapshot_agent()
        self.log("Replay complete. Comparing state of the agent and his "
                 "%d listeners.", len(listeners))
        self.assertEqual(agent_snapshot._get_state(), r.agent._get_state())

        listeners_from_replay = [obj for obj in r.registry.values()
                                 if obj.type_name.endswith('-medium')]

        self.assertEqual(len(listeners_from_replay), len(listeners))
        for from_snapshot, from_replay in zip(listeners,
                                              listeners_from_replay):
            self.assertEqual(from_snapshot._get_state(),
                             from_replay._get_state())

    @defer.inlineCallbacks
    def wait_for(self, check, timeout, freq=0.5):
        assert callable(check)
        waiting = 0

        while True:
            if check():
                break
            self.info('Check %r still negative, sleping %r seconds.',
                      check.__name__, freq)
            waiting += freq
            if waiting > timeout:
                raise FailTest('Timeout error waiting for check %r.',
                               check.__name__)
            yield common.delay(None, freq)

    def count_agents(self):
        return len([x for x in self.driver.iter_agents()])
