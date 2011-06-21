from feat.test.integration import common
from feat.agents.base import agent, descriptor, notifier, replay
from feat.common import defer, text_helper, time


@descriptor.register('notifier-agent')
class Descriptor(descriptor.Descriptor):
    pass


@agent.register('notifier-agent')
class Agent(agent.BaseAgent, notifier.AgentMixin):
    pass


@common.attr(timescale=0.05)
class TestNotifier(common.SimulationTest):

    timeout = 3

    @defer.inlineCallbacks
    def prolog(self):
        setup = text_helper.format_block("""
        agency = spawn_agency()
        agency.disable_protocol('setup-monitoring', 'Task')
        agency.start_agent(descriptor_factory('notifier-agent'), \
                           run_startup=False)
        """)
        yield self.process(setup)
        self.agent = self.get_local('_').get_agent()

    @defer.inlineCallbacks
    def testWaitCallbackAndErrback(self):
        # test callback
        d = self.agent.wait_for_event('event')
        self.assertIsInstance(d, defer.Deferred)
        self.agent.callback_event('event', 'result')
        result = yield d
        self.assertEqual('result', result)

        # test errback
        d = self.agent.wait_for_event('event2')
        self.agent.errback_event('event2', RuntimeError('failure'))
        self.assertFailure(d, RuntimeError)
        yield d

    @defer.inlineCallbacks
    def testTimeouts(self):
        d = self.agent.wait_for_event('event', timeout=0.05)
        d2 = self.agent.wait_for_event('event', timeout=2)
        self.assertFailure(d, notifier.TimeoutError)
        yield d

        # this should be safe
        self.agent.callback_event('event', 'result')
        res = yield d2
        self.assertEqual(res, 'result')
