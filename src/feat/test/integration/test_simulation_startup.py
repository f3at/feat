# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from feat import everything
from feat.common import first, defer
from feat.test.integration import common
from feat.common.text_helper import format_block
from feat.agents.base import (descriptor, agent, replay, document, )

from feat.agencies.interface import ConflictError


@agent.register('some-stupid-agent')
class SomeAgent(agent.BaseAgent):

    def initiate(self):
        agent.BaseAgent.initiate(self)
        return self.initiate_partners()

    @replay.mutable
    def do_sth_in_desc(self, state):

        def do_changes(desc):
            desc.field = 'sth'
            return desc

        return self.update_descriptor(do_changes)


@descriptor.register('some-stupid-agent')
class Descriptor(descriptor.Descriptor):

    document.field('field', None)


@common.attr(timescale=0.05)
class SimulateRunningAgentTwice(common.SimulationTest):

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        agency1 = spawn_agency()
        agency1.disable_protocol('setup-monitoring', 'Task')
        agency2 = spawn_agency()
        agency2.disable_protocol('setup-monitoring', 'Task')
        desc = descriptor_factory('some-stupid-agent')
        """)
        yield self.process(setup)
        self.agency1, self.agency2 = self.get_local('agency1', 'agency2')
        yield self.run_agent('agency1')

    def run_agent(self, agency):
        return self.process(format_block("""
        desc = reload_document(desc)
        %(agency)s.start_agent(desc)
        """) % {'agency': agency})

    def get_agent(self):
        self.assertEqual(1, self.count_agents('some-stupid-agent'))
        return first(self.driver.iter_agents('some-stupid-agent'))

    def get_agency(self):
        a = self.driver.find_agency(self.get_agent().get_descriptor().doc_id)
        return a

    @defer.inlineCallbacks
    def testStartingAgain(self):
        a = self.get_agency()
        self.assertEqual(a, self.agency1)
        self.info('Running agent second time')
        yield self.run_agent('agency2')
        yield self.wait_for_idle(5)
        a = self.get_agency()
        self.assertEqual(a, self.agency2)

        yield self.run_agent('agency1')
        yield self.wait_for_idle(5)
        a = self.get_agency()
        self.assertEqual(a, self.agency1)

    @defer.inlineCallbacks
    def testAgentGetsUpdateConflict(self):
        self.assertEqual(1, self.count_agents('some-stupid-agent'))

        # update descriptor remotely
        desc = self.get_local('desc')
        desc = yield self.driver.reload_document(desc)
        desc.instance_id += 1
        yield self.driver.save_document(desc)
        d = self.get_agent().get_agent().do_sth_in_desc()
        self.assertFailure(d, ConflictError)
        yield d
        yield self.wait_for_idle(3)
        self.assertEqual(0, self.count_agents('some-stupid-agent'))
