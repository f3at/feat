# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from twisted.trial.unittest import FailTest

from feat.common import fiber, defer
from feat.interface.agent import AgencyAgentState
from feat.agents.base import descriptor, agent, document
from feat.test import common


@descriptor.register('startup-test')
class Descriptor(descriptor.Descriptor):
    pass


@agent.register('startup-test')
class DummyAgent(agent.BaseAgent, common.Mock):

    def __init__(self, medium):
        agent.BaseAgent.__init__(self, medium)
        common.Mock.__init__(self)
        self._started_defer = defer.Deferred()

    @common.Mock.record
    def initiate(self, startup_fail=False):
        self.startup_fail = startup_fail

    @common.Mock.stub
    def shutdown(self):
        pass

    @common.Mock.record
    def startup(self):
        if self.startup_fail:
            raise BaseException('')
        return self._started_defer

    @common.Mock.stub
    def unregister(self):
        pass

    def set_started(self):
        self._started_defer.callback(self)

    def _wait_started(self, _):
        return self._started_defer


class TestStartupTask(common.TestCase, common.AgencyTestHelper):

    def setUp(self):
        common.AgencyTestHelper.setUp(self)

    @defer.inlineCallbacks
    def testAgentStartup(self):
        desc = yield self.doc_factory(Descriptor)
        dummy = yield self.agency.start_agent(desc)
        self.assertCalled(dummy.get_agent(), 'initiate')
        self.assertCalled(dummy.get_agent(), 'startup', times=0)
        self.assertEqual(dummy.get_machine_state(),
                         AgencyAgentState.initiated)
        dummy.get_agent().set_started()
        yield dummy.wait_for_state(AgencyAgentState.ready)
        self.assertCalled(dummy.get_agent(), 'startup', times=1)

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
        dummy = yield self.agency.start_agent(desc, startup_fail=True)
        yield dummy.wait_for_state(AgencyAgentState.error)
        self.assertEqual(dummy.get_machine_state(),
                         AgencyAgentState.error)
