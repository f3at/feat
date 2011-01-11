# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from feat.test import common
from feat.simulation import driver
from feat.agencies import replay


class IntegrationTest(common.TestCase):
    pass


class SimulationTest(common.TestCase):

    def setUp(self):
        self.driver = driver.Driver()
        return self.prolog()

    def process(self, script):
        d = self.cb_after(None, self.driver._parser, 'on_finish')
        self.driver.process(script)
        return d

    def get_local(self, name):
        return self.driver._parser.get_local(name)

    def tearDown(self):
        common.TestCase.tearDown(self)
        self.log("Test finished, now validating replayability.")
        for agency in self.driver._agencies:
            self._validate_replay_on_agency(agency)

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

        r = replay.Replay(entries.__iter__(), aid)
        for side_effects, result, output in r:
            self.assertTrue(side_effects is None,
                            "Remaining side effects %r" % side_effects)
            self.assertEqual(result, output)

        agent_snapshot, listeners = agent.snapshot_agent()
        self.log("Replay complete. Comparing state of the agent and his "
                 "%d listeners.", len(listeners))
        self.assertEqual(agent_snapshot._get_state(), r.agent._get_state())

        listeners_from_replay = [obj for obj in r.registry.values()\
                                 if obj.type_name.endswith('-medium')]
        if len(listeners) > 0:
            self.info(listeners[0])
        self.assertEqual(len(listeners_from_replay), len(listeners))
        for from_snapshot, from_replay in zip(listeners,
                                              listeners_from_replay):
            self.assertEqual(from_snapshot._get_state(),
                             from_replay._get_state())
