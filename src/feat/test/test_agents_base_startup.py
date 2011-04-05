# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from twisted.internet import defer
from twisted.trial.unittest import FailTest

from feat.interface.agent import AgencyAgentState
from feat.agents.base import descriptor, agent, document
from feat.test import common


@document.register
class Descriptor(descriptor.Descriptor):

    document_type = 'startup-error'


@agent.register('startup-error')
class DummyAgent(agent.BaseAgent, common.Mock):

    def __init__(self, medium):
        agent.BaseAgent.__init__(self, medium)
        common.Mock.__init__(self)

    @common.Mock.stub
    def initiate(self):
        pass

    @common.Mock.stub
    def shutdown(self):
        pass

    @common.Mock.record
    def startup(self):
        raise BaseException('')

    @common.Mock.stub
    def unregister(self):
        pass


class TestStartupTask(common.TestCase, common.AgencyTestHelper):

    def setUp(self):
        common.AgencyTestHelper.setUp(self)

    @defer.inlineCallbacks
    def testAgentStartup(self):
        desc = yield self.doc_factory(descriptor.Descriptor)
        dummy = yield self.agency.start_agent(desc)
        self.assertCalled(dummy.get_agent(), 'initiate')
        yield dummy.wait_for_state(AgencyAgentState.initiated)
        self.assertEqual(dummy.get_machine_state(),
                         AgencyAgentState.initiated)
        self.assertCalled(dummy.get_agent(), 'startup', times=0)
        yield dummy.wait_for_state(AgencyAgentState.starting_up)
        self.assertEqual(dummy.get_machine_state(),
                         AgencyAgentState.starting_up)
        yield dummy.wait_for_state(AgencyAgentState.ready)
        self.assertCalled(dummy.get_agent(), 'startup', times=1)
        self.assertEqual(dummy.get_machine_state(),
                         AgencyAgentState.ready)

    @defer.inlineCallbacks
    def testAgentNoStartup(self):
        desc = yield self.doc_factory(descriptor.Descriptor)
        dummy = yield self.agency.start_agent(desc, run_startup=False)
        yield dummy.wait_for_state(AgencyAgentState.ready)
        self.assertCalled(dummy.get_agent(), 'startup', times=0)
        self.assertEqual(dummy.get_machine_state(),
                         AgencyAgentState.ready)

    @defer.inlineCallbacks
    def testAgentFails(self):
        desc = yield self.doc_factory(Descriptor)
        dummy = yield self.agency.start_agent(desc)
        yield dummy.wait_for_state(AgencyAgentState.error)
        self.assertEqual(dummy.get_machine_state(),
                         AgencyAgentState.error)
