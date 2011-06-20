from twisted.internet import defer

from feat.test import common as test_common
from feat.test.integration import common

from feat.agents.base import agent, descriptor, replay, message
from feat.agents.base import requester, replier, notifier
from feat.common import fiber
from feat.common.text_helper import format_block
from feat.interface import protocols

from feat.interface.recipient import *


@descriptor.register("test_prop_agent")
class Descriptor(descriptor.Descriptor):
    pass


@agent.register("test_prop_agent")
class Agent(agent.BaseAgent, notifier.AgentMixin,
        test_common.Mock):

    @replay.mutable
    def initiate(self, state):
        test_common.Mock.__init__(self)
        state.medium.register_interest(LateReplier)

    @test_common.Mock.stub
    def called():
        pass


class LateRequester(requester.BaseRequester):

    protocol_id = 'test_late'
    timeout = 1

    @replay.entry_point
    def initiate(self, state):
        msg = message.RequestMessage()
        state.medium.request(msg)


class LateReplier(replier.BaseReplier):

    protocol_id = 'test_late'

    @replay.entry_point
    def requested(self, state, request):
        c = state.medium.get_canceller()
        f = fiber.Fiber(c)
        f.add_callback(fiber.drop_param,\
                state.agent.wait_for_event, "late event")
        f.add_callback(self.done)
        return f.succeed()

    @replay.mutable
    def done(self, state, _):
        # the following call is only used to make an assertion
        state.agent.called()
        response = message.ResponseMessage()
        state.medium.reply(response)


@common.attr(timescale=1)
@common.attr('slow')
class ProtoFiberCancelTest(common.SimulationTest):

    timeout = 5

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        agency = spawn_agency()
        agency.disable_protocol('setup-monitoring', 'Task')
        desc = descriptor_factory('test_prop_agent')
        medium = agency.start_agent(desc)
        agent = medium.get_agent()
        """)
        yield self.process(setup)

    def testValidateProlog(self):
        self.assertEqual(1, self.count_agents('test_prop_agent'))

    @defer.inlineCallbacks
    def testLateRequester(self):

        medium = self.get_local('medium')
        agent = self.get_local('agent')
        recip = IRecipient(agent)

        requester = agent.initiate_protocol(LateRequester, recip)

        d = requester.notify_finish()
        self.assertFailure(d, protocols.ProtocolExpired)
        yield d

        yield agent.callback_event("late event", None)

        self.assertCalled(agent, 'called', times=0)
